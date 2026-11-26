from __future__ import annotations

import pytest
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models.openai import OpenAIChatModel

from knowledge_agent.config import AgentModelSettings, Settings
from knowledge_agent.reasoning import (
    AgentError,
    AgentErrorKind,
    _limits_hit,
    build_model,
)


def test_unconfigured_model_fails_fast() -> None:
    settings = AgentModelSettings()

    with pytest.raises(AgentError) as exc_info:
        build_model(settings)

    assert exc_info.value.kind is AgentErrorKind.MODEL_CONFIG_ERROR


def test_model_uses_the_configured_compatible_provider() -> None:
    settings = Settings.from_env(
        {
            "AGENT_LLM_BASE_URL": "https://model.example.com/v1",
            "AGENT_LLM_MODEL": "vendor/model",
            "AGENT_LLM_API_KEY": "secret",
        }
    )

    model = build_model(settings.llm)

    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "vendor/model"
    assert "secret" not in repr(model)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "The next request would exceed the request_limit of 2",
            ("model_requests",),
        ),
        (
            "The next request would exceed the total_tokens_limit of 1000",
            ("tokens",),
        ),
        ("unknown limit", ("model_requests", "tokens")),
    ],
)
def test_usage_limit_exhaustion_is_classified(
    message: str, expected: tuple[str, ...]
) -> None:
    assert _limits_hit(UsageLimitExceeded(message)) == expected


def test_error_kinds_are_stable() -> None:
    assert {kind.value for kind in AgentErrorKind} == {
        "model_config_error",
        "model_unavailable",
        "model_timeout",
        "model_limit",
        "model_output_invalid",
    }
