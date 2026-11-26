"""A2A executor for the knowledge search agent."""

from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TextPart

from knowledge_agent.config import Settings

SCAFFOLD_MESSAGE = (
    "Knowledge Search Agent scaffold is running. "
    "The LCORE-backed search workflow is not implemented yet."
)


class KnowledgeSearchExecutor(AgentExecutor):
    """Placeholder executor replaced by the bounded workflow."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

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
        await updater.start_work()
        await updater.add_artifact(
            parts=[Part(root=TextPart(text=SCAFFOLD_MESSAGE))],
            last_chunk=True,
        )
        await updater.complete()

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise NotImplementedError("task cancellation is not supported")
