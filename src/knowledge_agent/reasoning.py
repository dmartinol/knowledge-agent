"""Agent-owned reasoning: the pydantic-ai typed tool loop.

See `docs/workflow-loop.md` for the loop shape and its component mapping.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, ModelSettings, RunContext
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelNotFoundError,
    ModelTimeoutError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai_compatible import OpenAICompatibleProvider
from pydantic_ai.usage import UsageLimits

from knowledge_agent.config import AgentModelSettings, Settings
from knowledge_agent.loop import (
    SearchObservation,
    SearchState,
)
from knowledge_agent.loop import (
    search_knowledge as run_search,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "knowledge-agent-llm"
MAX_GAPS = 6

FORBIDDEN_SECTION = re.compile(
    r"(?im)^\s*(sources|references|citations|gaps)\s*:"
)
URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)

class ClarificationRequest(BaseModel):
    """One question that asks for the detail needed before searching."""

    kind: Literal["clarification"] = "clarification"
    question: str = Field(
        description="One short question asking only for the missing detail."
    )


class KnowledgeAnswer(BaseModel):
    """The answer for the caller, without citations or rendered sections."""

    kind: Literal["answer"] = "answer"
    answer: str = Field(
        description=(
            "Plain prose answer for the caller. No headings, no URLs, and no "
            "Sources, References, Citations, or Gaps sections."
        )
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Short statements about what the search material did not cover.",
    )


AgentDecision = Annotated[
    ClarificationRequest | KnowledgeAnswer, Field(discriminator="kind")
]


class AgentErrorKind(StrEnum):
    """Stable failure categories for the reasoning plane."""

    MODEL_CONFIG_ERROR = "model_config_error"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_LIMIT = "model_limit"
    MODEL_OUTPUT_INVALID = "model_output_invalid"


class AgentError(Exception):
    """Normalized reasoning failure without exposing prompts or model output."""

    def __init__(
        self,
        kind: AgentErrorKind,
        message: str,
        *,
        limits_hit: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.limits_hit = limits_hit


@dataclass(frozen=True)
class ReasoningOutcome:
    """Validated model decision plus observable usage."""

    decision: ClarificationRequest | KnowledgeAnswer
    requests: int
    tokens: int


def build_model(settings: AgentModelSettings) -> Model:
    """Build the agent-owned OpenAI-compatible model or fail fast."""
    if not settings.configured:
        raise AgentError(
            AgentErrorKind.MODEL_CONFIG_ERROR,
            "The reasoning model is not configured.",
        )
    return OpenAIChatModel(
        settings.model,
        provider=OpenAICompatibleProvider(
            PROVIDER_NAME,
            base_url=settings.base_url,
            api_key=settings.api_key.get_secret_value(),
        ),
    )


def build_agent(
    model: Model, settings: AgentModelSettings, instructions: str
) -> Agent[SearchState, AgentDecision]:
    """Create the typed tool-loop agent with code-owned validation."""
    agent: Agent[SearchState, AgentDecision] = Agent(
        model,
        deps_type=SearchState,
        output_type=AgentDecision,
        instructions=instructions,
        model_settings=ModelSettings(timeout=settings.timeout_seconds),
        retries={"output": 2, "tools": 0},
    )

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[SearchState], query: str
    ) -> SearchObservation:
        """Search the configured knowledge service once and return its material."""
        text = query.strip()
        if not text:
            raise ModelRetry("The search query must not be empty.")
        return await run_search(ctx.deps, text)

    @agent.output_validator
    def validate_decision(
        ctx: RunContext[SearchState], decision: AgentDecision
    ) -> AgentDecision:
        state = ctx.deps
        if isinstance(decision, ClarificationRequest):
            question = decision.question.strip()
            if not question:
                raise ModelRetry("The clarification question must not be empty.")
            if state.clarification_used:
                raise ModelRetry(
                    "The one clarification was already used. Search the "
                    "knowledge service and answer."
                )
            if state.searches:
                raise ModelRetry(
                    "A clarification is not possible after a search. Answer "
                    "from the material you already have."
                )
            return ClarificationRequest(question=question)

        answer = decision.answer.strip()
        if not answer:
            raise ModelRetry("The answer must not be empty.")
        if not state.searches:
            raise ModelRetry("Call search_knowledge before answering.")
        if FORBIDDEN_SECTION.search(answer):
            raise ModelRetry(
                "Remove the Sources, References, Citations, or Gaps heading: "
                "the service renders those sections."
            )
        if URL_PATTERN.search(answer):
            raise ModelRetry(
                "Remove URLs from the answer: citations are rendered by the "
                "service."
            )
        gaps = [gap.strip() for gap in decision.gaps if gap.strip()][:MAX_GAPS]
        return KnowledgeAnswer(answer=answer, gaps=gaps)

    return agent


async def run_reasoning(
    settings: Settings,
    state: SearchState,
    prompt: str,
    *,
    instructions: str,
    model: Model | None = None,
) -> ReasoningOutcome:
    """Run one typed tool loop and normalize provider failures."""
    llm = settings.llm
    resolved_model = model if model is not None else build_model(llm)
    agent = build_agent(resolved_model, llm, instructions)
    try:
        result = await agent.run(
            prompt,
            deps=state,
            usage_limits=UsageLimits(
                request_limit=llm.request_limit,
                total_tokens_limit=llm.total_tokens_limit,
            ),
        )
    except UsageLimitExceeded as exc:
        raise AgentError(
            AgentErrorKind.MODEL_LIMIT,
            "The reasoning model exhausted its configured limits.",
            limits_hit=_limits_hit(exc),
        ) from exc
    except ModelTimeoutError as exc:
        raise AgentError(
            AgentErrorKind.MODEL_TIMEOUT, "The reasoning model timed out."
        ) from exc
    except (ModelAuthenticationError, ModelNotFoundError) as exc:
        raise AgentError(
            AgentErrorKind.MODEL_CONFIG_ERROR,
            "The reasoning model rejected the configured credentials or model.",
        ) from exc
    except UnexpectedModelBehavior as exc:
        raise AgentError(
            AgentErrorKind.MODEL_OUTPUT_INVALID,
            "The reasoning model did not return a usable answer.",
        ) from exc
    except ModelConnectionError as exc:
        raise AgentError(
            AgentErrorKind.MODEL_UNAVAILABLE,
            "The reasoning model could not be reached.",
        ) from exc
    except ModelAPIError as exc:
        raise AgentError(
            AgentErrorKind.MODEL_UNAVAILABLE,
            "The reasoning model returned an error.",
        ) from exc

    usage = result.usage
    logger.info(
        "Reasoning finished: model=%s requests=%d tokens=%d searches=%d",
        llm.model,
        usage.requests,
        usage.total_tokens,
        state.searches,
    )
    return ReasoningOutcome(
        decision=result.output,
        requests=usage.requests,
        tokens=usage.total_tokens,
    )


def _limits_hit(exc: UsageLimitExceeded) -> tuple[str, ...]:
    message = str(exc)
    if "request_limit" in message:
        return ("model_requests",)
    if "tokens_limit" in message:
        return ("tokens",)
    return ("model_requests", "tokens")
