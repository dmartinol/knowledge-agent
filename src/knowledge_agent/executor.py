"""A2A executor for the bounded knowledge search workflow."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, Part, TaskState, TextPart

from knowledge_agent.config import Settings
from knowledge_agent.consolidation import consolidate_answer
from knowledge_agent.lcore_client import LcoreError, LcoreErrorKind
from knowledge_agent.workflow import (
    DEADLINE_LIMITATION,
    WORKFLOW_METADATA_KEY,
    SearchClient,
    WorkflowProgress,
    WorkflowResult,
    build_result,
    clarification_metadata,
    clarification_question,
    compose_query,
    needs_clarification,
    read_clarification_question,
    run_workflow,
)

logger = logging.getLogger(__name__)

ERROR_MESSAGES = {
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
GENERIC_ERROR_MESSAGE = "The knowledge search workflow failed."
CAPACITY_MESSAGE = "The agent is at capacity; please retry later."
DEADLINE_MESSAGE = (
    "The workflow deadline was reached before a search result was available."
)
EMPTY_REQUEST_MESSAGE = "I need a concrete question to search for."


class KnowledgeSearchExecutor(AgentExecutor):
    """Run a bounded decide-search-observe loop over the LCORE client."""

    def __init__(
        self,
        settings: Settings,
        client: SearchClient,
        *,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
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
            clarification: str | None = user_input
        else:
            if needs_clarification(user_input):
                await updater.update_status(
                    TaskState.input_required,
                    message=self._message(
                        updater, clarification_question(user_input)
                    ),
                    final=False,
                    metadata=clarification_metadata(user_input),
                )
                return
            question = user_input
            clarification = None

        await updater.start_work()
        limits = self._settings.workflow
        progress = WorkflowProgress()
        consolidated_question = compose_query(question, clarification)
        acquired = False
        try:
            async with asyncio.timeout(limits.task_deadline_seconds):
                await self._semaphore.acquire()
                acquired = True
                try:
                    result = await run_workflow(
                        self._client,
                        policy=limits.follow_up_policy,
                        max_rounds=limits.max_rounds,
                        question=question,
                        clarification=clarification,
                        progress=progress,
                    )
                    if len(progress.results) > 1:
                        result = await self._consolidate(
                            result,
                            question=consolidated_question,
                            progress=progress,
                        )
                finally:
                    self._semaphore.release()
        except TimeoutError:
            if not acquired:
                await updater.reject(self._message(updater, CAPACITY_MESSAGE))
                return
            if not progress.results:
                await updater.failed(self._message(updater, DEADLINE_MESSAGE))
                return
            result = build_result(
                progress.results,
                policy=limits.follow_up_policy,
                searches=progress.searches,
                follow_up="skipped_limit",
                extra_limitations=(DEADLINE_LIMITATION,),
                consolidation=(
                    "fallback"
                    if len(progress.results) > 1
                    else "skipped_single_result"
                ),
            )
        except LcoreError as exc:
            logger.warning(
                "LCORE search failed: kind=%s status=%s rpc_code=%s task_state=%s",
                exc.kind,
                exc.status_code,
                exc.rpc_code,
                exc.task_state,
            )
            await updater.update_status(
                TaskState.failed,
                message=self._message(
                    updater,
                    ERROR_MESSAGES.get(exc.kind, GENERIC_ERROR_MESSAGE),
                ),
                metadata={WORKFLOW_METADATA_KEY: {"error": exc.kind.value}},
            )
            return

        logger.info(
            "Knowledge search finished: searches=%d evidence_status=%s follow_up=%s",
            result.searches,
            result.evidence_status,
            result.follow_up,
        )
        await updater.add_artifact(
            parts=[Part(root=TextPart(text=result.text))],
            name="knowledge-search-answer",
            metadata={WORKFLOW_METADATA_KEY: result.metadata},
            last_chunk=True,
        )
        await updater.complete()

    async def _consolidate(
        self,
        result: WorkflowResult,
        *,
        question: str,
        progress: WorkflowProgress,
    ) -> WorkflowResult:
        """Merge multiple answers with the fixed template, or fall back."""
        limits = self._settings.workflow
        try:
            consolidated = await consolidate_answer(
                self._client,
                question=question,
                results=progress.results,
            )
        except LcoreError as exc:
            logger.warning(
                "LCORE consolidation failed: kind=%s status=%s",
                exc.kind,
                exc.status_code,
            )
            return replace(result, consolidation="fallback")
        if consolidated is None:
            return replace(result, consolidation="fallback")
        return build_result(
            progress.results,
            policy=limits.follow_up_policy,
            searches=result.searches,
            follow_up=result.follow_up,
            answer_text=consolidated,
            consolidation="llm",
        )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise NotImplementedError("task cancellation is not supported")

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
