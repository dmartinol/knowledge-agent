import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

from knowledge_agent.config import Settings
from knowledge_agent.lcore_client import LcoreClient
from knowledge_agent.lcore_rest import RestLcoreClient
from knowledge_agent.server import build_search_client, create_app


@pytest.fixture
def app():
    return create_app(Settings.from_env({}))


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client


def _message_send(text: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": "test-1",
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": str(uuid.uuid4()),
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }


def test_default_transport_is_a2a() -> None:
    assert isinstance(build_search_client(Settings.from_env({})), LcoreClient)


def test_rest_transport_is_selected() -> None:
    settings = Settings.from_env(
        {
            "LCORE_RETRIEVER": "rest",
            "LCORE_REST_URL": "http://lcore.test:8080",
        }
    )

    assert isinstance(build_search_client(settings), RestLcoreClient)


@pytest.mark.parametrize(
    "path", ["/.well-known/agent-card.json", "/.well-known/agent.json"]
)
async def test_agent_card_is_served(client: httpx.AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 200
    card = response.json()
    assert card["name"] == "Knowledge Search Agent"
    assert card["url"] == "http://127.0.0.1:8081/a2a"
    assert card["protocolVersion"] == "0.3.0"
    assert card["preferredTransport"] == "JSONRPC"
    assert card["capabilities"]["streaming"] is False
    assert card["security"] == []
    assert card["skills"][0]["id"] == "knowledge-search"


async def test_health_reports_service_and_version(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/a2a/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


async def test_unknown_method_returns_jsonrpc_error(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/a2a", json={"jsonrpc": "2.0", "id": "x", "method": "tasks/bogus"}
    )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32601


async def test_invalid_params_return_jsonrpc_error(
    client: httpx.AsyncClient,
) -> None:
    payload = {"jsonrpc": "2.0", "id": "y", "method": "message/send", "params": {}}
    response = await client.post("/a2a", json=payload)

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32602
