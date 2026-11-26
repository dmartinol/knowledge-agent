"""Agent Card published by the knowledge search service."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from knowledge_agent.config import Settings

AGENT_NAME = "Knowledge Search Agent"
SKILL_ID = "knowledge-search"
PROTOCOL_VERSION = "0.3.0"
FALLBACK_VERSION = "0.1.0"


def _package_version() -> str:
    try:
        return version("knowledge-agent")
    except PackageNotFoundError:
        return FALLBACK_VERSION


def build_agent_card(settings: Settings) -> AgentCard:
    return AgentCard(
        name=AGENT_NAME,
        description=(
            "Evidence-aware knowledge search that answers through Lightspeed "
            "Core Stack over A2A."
        ),
        url=settings.rpc_url,
        version=_package_version(),
        protocol_version=PROTOCOL_VERSION,
        preferred_transport="JSONRPC",
        capabilities=AgentCapabilities(
            streaming=False,
            push_notifications=False,
            state_transition_history=False,
        ),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        security=[],
        security_schemes={},
        skills=[
            AgentSkill(
                id=SKILL_ID,
                name="Knowledge Search",
                description=(
                    "Searches the knowledge sources configured in LCORE and "
                    "answers with the evidence it can verify."
                ),
                tags=["knowledge-search", "red-hat"],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
            )
        ],
    )
