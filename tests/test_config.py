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
    assert limits.max_material_chars == 12_000
    assert limits.upstream_timeout_seconds == 90
    assert limits.task_deadline_seconds == 180
    assert limits.max_concurrent_tasks == 4
    assert settings.skills_dir == "skills"
    assert settings.retriever.value == "a2a"
    assert settings.lcore_rest_url == "http://localhost:8080"
    assert settings.llm.configured is False
    assert settings.llm.request_limit == 6
    assert settings.llm.total_tokens_limit == 60_000
    assert settings.llm.timeout_seconds == 60


def test_environment_overrides() -> None:
    settings = Settings.from_env(
        {
            "HOST": "0.0.0.0",
            "PORT": "9000",
            "LCORE_AGENT_CARD_URL": "http://lcore.internal:8080/.well-known/agent-card.json",
            "WORKFLOW_MAX_ROUNDS": "1",
            "WORKFLOW_MAX_MATERIAL_CHARS": "4000",
            "WORKFLOW_UPSTREAM_TIMEOUT_SECONDS": "45",
            "WORKFLOW_TASK_DEADLINE_SECONDS": "60",
            "WORKFLOW_MAX_CONCURRENT_TASKS": "8",
            "AGENT_LLM_BASE_URL": "https://model.example.com/v1",
            "AGENT_LLM_MODEL": "vendor/model",
            "AGENT_LLM_API_KEY": "secret",
            "AGENT_LLM_TIMEOUT_SECONDS": "30",
            "AGENT_LLM_REQUEST_LIMIT": "4",
            "AGENT_LLM_TOTAL_TOKENS_LIMIT": "9000",
        }
    )

    assert settings.public_url == "http://0.0.0.0:9000"
    assert settings.lcore_agent_card_url.startswith("http://lcore.internal")
    assert settings.workflow.max_rounds == 1
    assert settings.workflow.max_material_chars == 4000
    assert settings.workflow.upstream_timeout_seconds == 45
    assert settings.workflow.task_deadline_seconds == 60
    assert settings.workflow.max_concurrent_tasks == 8
    assert settings.llm.configured is True
    assert settings.llm.base_url == "https://model.example.com/v1"
    assert settings.llm.model == "vendor/model"
    assert settings.llm.request_limit == 4
    assert settings.llm.total_tokens_limit == 9000
    assert settings.llm.timeout_seconds == 30


def test_model_configuration_falls_back_to_existing_variables() -> None:
    settings = Settings.from_env(
        {
            "OPENAI_BASE_URL": "https://fallback.example.com/v1",
            "E2E_OPENAI_MODEL": "fallback-model",
            "OPENAI_API_KEY": "fallback-key",
        }
    )

    assert settings.llm.configured is True
    assert settings.llm.base_url == "https://fallback.example.com/v1"
    assert settings.llm.model == "fallback-model"
    assert settings.llm.api_key.get_secret_value() == "fallback-key"


def test_partial_model_configuration_is_rejected() -> None:
    with pytest.raises(ConfigError, match="AGENT_LLM_MODEL"):
        Settings.from_env({"AGENT_LLM_BASE_URL": "https://model.example.com/v1"})


def test_ambient_api_key_alone_does_not_break_configuration() -> None:
    settings = Settings.from_env({"OPENAI_API_KEY": "ambient-key"})

    assert settings.skills_dir == "skills"
    assert settings.llm.configured is False


def test_invalid_model_base_url_is_rejected() -> None:
    with pytest.raises(ConfigError, match="AGENT_LLM_BASE_URL"):
        Settings.from_env(
            {
                "AGENT_LLM_BASE_URL": "model.example.com",
                "AGENT_LLM_MODEL": "vendor/model",
                "AGENT_LLM_API_KEY": "secret",
            }
        )


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


def test_more_than_one_follow_up_is_rejected() -> None:
    with pytest.raises(ConfigError, match="WORKFLOW_MAX_ROUNDS"):
        Settings.from_env({"WORKFLOW_MAX_ROUNDS": "3"})


def test_zero_material_limit_is_rejected() -> None:
    with pytest.raises(ConfigError, match="max_material_chars"):
        Settings.from_env({"WORKFLOW_MAX_MATERIAL_CHARS": "0"})


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


def test_rest_retriever_is_selected_and_normalized() -> None:
    settings = Settings.from_env(
        {
            "LCORE_RETRIEVER": " REST ",
            "LCORE_REST_URL": "http://lcore.internal:8080/",
        }
    )

    assert settings.retriever.value == "rest"
    assert settings.lcore_rest_url == "http://lcore.internal:8080"


def test_unknown_retriever_is_rejected() -> None:
    with pytest.raises(ConfigError, match="LCORE_RETRIEVER"):
        Settings.from_env({"LCORE_RETRIEVER": "grpc"})


def test_relative_rest_url_is_rejected() -> None:
    with pytest.raises(ConfigError, match="LCORE_REST_URL"):
        Settings.from_env({"LCORE_REST_URL": "/v1/query"})


def test_skills_directory_override() -> None:
    settings = Settings.from_env({"AGENT_SKILLS_DIR": " /srv/skills "})

    assert settings.skills_dir == "/srv/skills"


def test_empty_skills_directory_is_rejected() -> None:
    with pytest.raises(ConfigError, match="AGENT_SKILLS_DIR"):
        Settings.from_env({"AGENT_SKILLS_DIR": "   "})
