"""A2A executor for the agent-owned knowledge search loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, Part, TaskState, TextPart
from pydantic_ai.models import Model

from knowledge_agent.config import Settings
from knowledge_agent.lcore_client import LcoreErrorKind
from knowledge_agent.loop import (
    EMPTY_REQUEST_MESSAGE,
    WORKFLOW_METADATA_KEY,
    SearchClient,
    SearchState,
    clarification_metadata,
    compose_prompt,
    read_clarification_question,
)
from knowledge_agent.reasoning import (
    AgentError,
    AgentErrorKind,
    ClarificationRequest,
    run_reasoning,
)
from knowledge_agent.render import render_answer

logger = logging.getLogger(__name__)

LCORE_ERROR_MESSAGES = {
    LcoreErrorKind.CARD_UNAVAILABLE: (
        "The upstream knowledge service could not be reached."
    ),
    LcoreErrorKind.PROTOCOL_UNSUPPORTED: (
        "The upstream knowledge service uses an unsupported A2A protocol."
    ),
    LcoreErrorKind.TIMEOUT: "The upstream knowledge service timed out.",
    LcoreErrorKind.HTTP_ERROR: (
        "The upstream knowledge service returned an HTTP error."
    ),
    LcoreErrorKind.JSONRPC_ERROR: (
        "The upstream knowledge service returned an error response."
    ),
    LcoreErrorKind.TASK_NOT_COMPLETED: (
        "The upstream knowledge service did not complete the search."
    ),
    LcoreErrorKind.INVALID_RESPONSE: (
        "The upstream knowledge service returned an unusable response."
    ),
}
AGENT_ERROR_MESSAGES = {
    AgentErrorKind.MODEL_CONFIG_ERROR: "The reasoning model is not configured.",
    AgentErrorKind.MODEL_UNAVAILABLE: "The reasoning model could not be reached.",
    AgentErrorKind.MODEL_TIMEOUT: "The reasoning model timed out.",
    AgentErrorKind.MODEL_LIMIT: (
        "The reasoning model reached its configured limit."
    ),
    AgentErrorKind.MODEL_OUTPUT_INVALID: (
        "The reasoning model did not produce a usable answer."
    ),
}
GENERIC_ERROR_MESSAGE = "The knowledge search workflow failed."
CAPACITY_MESSAGE = "The agent is at capacity; please retry later."
DEADLINE_MESSAGE = "The workflow deadline was reached before an answer was ready."


class KnowledgeSearchExecutor(AgentExecutor):
    """Run one bounded agent-owned reasoning loop per A2A task."""

    def __init__(
        self,
        settings: Settings,
        client: SearchClient,
        *,
        model: Model | None = None,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._model = model
        self._semaphore = (
            semaphore
            if semaphore is not None
            else asyncio.Semaphore(settings.workflow.max_concurrent_tasks)
        )

    @property
    def settings(self) -> Settings:
        return self._settings

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        updater = TaskUpdater(
            event_queue,
            context.task_id or "",
            context.context_id or "",
        )
        await updater.submit()

        user_input = context.get_user_input().strip()
        previous = context.current_task
        pending_question = read_clarification_question(
            previous.metadata if previous is not None else None
        )

        if pending_question is not None:
            if not user_input:
                await updater.start_work()
                await self._complete_with_text(updater, EMPTY_REQUEST_MESSAGE)
                return
            question = pending_question
            clarification_used = True
            prompt = compose_prompt(question, user_input)
        else:
            if not user_input:
                await updater.start_work()
                await self._complete_with_text(updater, EMPTY_REQUEST_MESSAGE)
                return
            question = user_input
            clarification_used = False
            prompt = user_input

        await updater.start_work()
        limits = self._settings.workflow
        state = SearchState(
            client=self._client,
            max_searches=limits.max_rounds,
            clarification_used=clarification_used,
        )
        acquired = False
        try:
            async with asyncio.timeout(limits.task_deadline_seconds):
                await self._semaphore.acquire()
                acquired = True
                try:
                    outcome = await run_reasoning(
                        self._settings, state, prompt, model=self._model
                    )
                finally:
                    self._semaphore.release()
        except TimeoutError:
            if not acquired:
                await updater.reject(self._message(updater, CAPACITY_MESSAGE))
                return
            await self._fail(
                updater,
                DEADLINE_MESSAGE,
                "deadline",
                limits_hit=("deadline",),
            )
            return
        except AgentError as exc:
            logger.warning(
                "Reasoning failed: kind=%s limits=%s",
                exc.kind,
                exc.limits_hit,
            )
            await self._fail(
                updater,
                AGENT_ERROR_MESSAGES.get(exc.kind, GENERIC_ERROR_MESSAGE),
                exc.kind.value,
                limits_hit=exc.limits_hit,
            )
            return

        if state.failure is not None:
            failure = state.failure
            logger.warning(
                "LCORE search failed: kind=%s status=%s rpc_code=%s task_state=%s",
                failure.kind,
                failure.status_code,
                failure.rpc_code,
                failure.task_state,
            )
            await self._fail(
                updater,
                LCORE_ERROR_MESSAGES.get(failure.kind, GENERIC_ERROR_MESSAGE),
                failure.kind.value,
            )
            return

        decision = outcome.decision
        if isinstance(decision, ClarificationRequest):
            await updater.update_status(
                TaskState.input_required,
                message=self._message(updater, decision.question),
                final=False,
                metadata=clarification_metadata(question),
            )
            return

        rendered = render_answer(
            decision, state, requests=outcome.requests, tokens=outcome.tokens
        )
        logger.info(
            "Knowledge search finished: searches=%d evidence_status=%s "
            "requests=%d",
            state.searches,
            rendered.metadata["evidence_status"],
            outcome.requests,
        )
        await updater.add_artifact(
            parts=[Part(root=TextPart(text=rendered.text))],
            name="knowledge-search-answer",
            metadata={WORKFLOW_METADATA_KEY: rendered.metadata},
            last_chunk=True,
        )
        await updater.complete()

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise NotImplementedError("task cancellation is not supported")

    async def _fail(
        self,
        updater: TaskUpdater,
        text: str,
        error: str,
        *,
        limits_hit: Sequence[str] = (),
    ) -> None:
        metadata: dict[str, object] = {"error": error}
        if limits_hit:
            metadata["limits_hit"] = list(limits_hit)
        await updater.update_status(
            TaskState.failed,
            message=self._message(updater, text),
            metadata={WORKFLOW_METADATA_KEY: metadata},
        )

    async def _complete_with_text(
        self, updater: TaskUpdater, text: str
    ) -> None:
        await updater.add_artifact(
            parts=[Part(root=TextPart(text=text))],
            name="knowledge-search-answer",
            last_chunk=True,
        )
        await updater.complete()

    @staticmethod
    def _message(updater: TaskUpdater, text: str) -> Message:
        return updater.new_agent_message([Part(root=TextPart(text=text))])
