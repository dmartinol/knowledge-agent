from __future__ import annotations

import logging

from knowledge_agent.__main__ import _log_startup
from knowledge_agent.config import Settings
from knowledge_agent.skills import LoadedSkill, SkillBundle


def test_startup_log_reports_model_endpoints_and_skills(
    caplog,
) -> None:
    settings = Settings.from_env(
        {
            "AGENT_LLM_BASE_URL": "https://model.example.com/v1",
            "AGENT_LLM_MODEL": "vendor/model",
            "AGENT_LLM_API_KEY": "secret-value",
            "LCORE_AGENT_CARD_URL": "http://lcore.internal:8080/.well-known/agent-card.json",
        }
    )
    bundle = SkillBundle(
        instructions="instructions",
        skills=(
            LoadedSkill(name="knowledge-search", version="2", digest="a" * 64),
            LoadedSkill(name="answer-synthesis", version="2", digest="b" * 64),
        ),
    )

    with caplog.at_level(logging.INFO, logger="knowledge_agent"):
        _log_startup(settings, bundle)

    text = caplog.text
    assert "model=vendor/model" in text
    assert "provider=https://model.example.com/v1" in text
    assert "public_url=http://127.0.0.1:8081" in text
    assert "lcore_card=http://lcore.internal:8080/.well-known/agent-card.json" in text
    assert "knowledge-search@2 sha256=aaaaaaaaaaaa" in text
    assert "answer-synthesis@2 sha256=bbbbbbbbbbbb" in text
    assert "secret-value" not in text
