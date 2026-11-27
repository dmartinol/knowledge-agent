"""FastAPI application exposing the A2A surface."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import cast

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from fastapi import FastAPI
from pydantic_ai.models import Model
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Route

from knowledge_agent.agent_card import build_agent_card
from knowledge_agent.config import RetrieverKind, Settings
from knowledge_agent.executor import KnowledgeSearchExecutor
from knowledge_agent.lcore_client import LcoreClient
from knowledge_agent.lcore_rest import RestLcoreClient
from knowledge_agent.loop import ClosableSearchClient, SearchClient
from knowledge_agent.skills import SkillBundle

RPC_PATH = "/a2a"
HEALTH_PATH = "/a2a/health"
CARD_PREFIX = "/.well-known/"

Endpoint = Callable[[Request], Awaitable[Response]]


def build_search_client(settings: Settings) -> ClosableSearchClient:
    """Select the configured LCORE retrieval transport once at startup."""
    if settings.retriever is RetrieverKind.REST:
        return RestLcoreClient(settings)
    return LcoreClient(settings)


def _find_endpoint(
    routes: Sequence[BaseRoute], path: str, method: str
) -> Endpoint:
    for route in routes:
        if (
            isinstance(route, Route)
            and route.path == path
            and method in (route.methods or set())
        ):
            return cast(Endpoint, route.endpoint)
    raise RuntimeError(f"A2A SDK application is missing the {method} {path} route")


def create_app(
    settings: Settings,
    *,
    search_client: SearchClient | None = None,
    model: Model | None = None,
    skills: SkillBundle | None = None,
) -> FastAPI:
    card = build_agent_card(settings)
    owned_client: ClosableSearchClient | None = None
    client: SearchClient
    if search_client is None:
        owned_client = build_search_client(settings)
        client = owned_client
    else:
        client = search_client

    handler = DefaultRequestHandler(
        agent_executor=KnowledgeSearchExecutor(
            settings, client, model=model, skills=skills
        ),
        task_store=InMemoryTaskStore(),
    )
    sdk_app = A2AStarletteApplication(
        agent_card=card,
        http_handler=handler,
    ).build()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if owned_client is not None:
            await owned_client.aclose()

    app = FastAPI(title=card.name, version=card.version, lifespan=lifespan)

    app.add_api_route(
        RPC_PATH,
        _find_endpoint(sdk_app.routes, "/", "POST"),
        methods=["POST"],
        include_in_schema=False,
    )
    for route in sdk_app.routes:
        if isinstance(route, Route) and route.path.startswith(CARD_PREFIX):
            app.add_api_route(
                route.path,
                cast(Endpoint, route.endpoint),
                methods=sorted(route.methods or {"GET"}),
                include_in_schema=False,
            )

    @app.get(HEALTH_PATH)
    async def health() -> dict[str, str]:
        return {
            "status": "healthy",
            "service": "knowledge-search-agent",
            "version": card.version,
        }

    return app
