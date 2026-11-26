import pytest

from knowledge_agent.config import ConfigError, Settings


def test_defaults() -> None:
    settings = Settings.from_env({})

    assert settings.host == "127.0.0.1"
    assert settings.port == 8081
    assert settings.public_url == "http://127.0.0.1:8081"
    assert settings.rpc_url == "http://127.0.0.1:8081/a2a"
    assert (
        settings.lcore_agent_card_url
        == "http://localhost:8080/.well-known/agent-card.json"
    )
    limits = settings.workflow
    assert limits.max_rounds == 2
    assert limits.upstream_timeout_seconds == 90
    assert limits.task_deadline_seconds == 180
    assert limits.max_concurrent_tasks == 4


def test_environment_overrides() -> None:
    settings = Settings.from_env(
        {
            "HOST": "0.0.0.0",
            "PORT": "9000",
            "LCORE_AGENT_CARD_URL": "http://lcore.internal:8080/.well-known/agent-card.json",
            "WORKFLOW_MAX_ROUNDS": "3",
            "WORKFLOW_UPSTREAM_TIMEOUT_SECONDS": "45",
            "WORKFLOW_TASK_DEADLINE_SECONDS": "60",
            "WORKFLOW_MAX_CONCURRENT_TASKS": "8",
        }
    )

    assert settings.public_url == "http://0.0.0.0:9000"
    assert settings.lcore_agent_card_url.startswith("http://lcore.internal")
    assert settings.workflow.max_rounds == 3
    assert settings.workflow.upstream_timeout_seconds == 45
    assert settings.workflow.task_deadline_seconds == 60
    assert settings.workflow.max_concurrent_tasks == 8


def test_public_url_override_wins_and_is_normalized() -> None:
    settings = Settings.from_env({"PUBLIC_URL": "https://agent.example.com/"})

    assert settings.public_url == "https://agent.example.com"
    assert settings.rpc_url == "https://agent.example.com/a2a"


def test_host_and_port_arguments_override_environment() -> None:
    settings = Settings.from_env(
        {"HOST": "127.0.0.1", "PORT": "8081"}, host="localhost", port=7000
    )

    assert settings.host == "localhost"
    assert settings.port == 7000
    assert settings.public_url == "http://localhost:7000"


def test_non_numeric_limit_is_rejected() -> None:
    with pytest.raises(ConfigError, match="WORKFLOW_MAX_ROUNDS"):
        Settings.from_env({"WORKFLOW_MAX_ROUNDS": "two"})


def test_zero_limit_is_rejected() -> None:
    with pytest.raises(ConfigError, match="max_concurrent_tasks"):
        Settings.from_env({"WORKFLOW_MAX_CONCURRENT_TASKS": "0"})


def test_upstream_timeout_above_deadline_is_rejected() -> None:
    with pytest.raises(ConfigError, match="WORKFLOW_UPSTREAM_TIMEOUT_SECONDS"):
        Settings.from_env(
            {
                "WORKFLOW_UPSTREAM_TIMEOUT_SECONDS": "120",
                "WORKFLOW_TASK_DEADLINE_SECONDS": "60",
            }
        )


def test_relative_lcore_url_is_rejected() -> None:
    with pytest.raises(ConfigError, match="LCORE_AGENT_CARD_URL"):
        Settings.from_env({"LCORE_AGENT_CARD_URL": "/agent-card.json"})
