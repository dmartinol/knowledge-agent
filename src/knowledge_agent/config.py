"""Runtime configuration for the knowledge search agent."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Self
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

DEFAULT_LCORE_AGENT_CARD_URL = "http://localhost:8080/.well-known/agent-card.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8081
DEFAULT_MAX_ROUNDS = 2
DEFAULT_UPSTREAM_TIMEOUT_SECONDS = 90
DEFAULT_TASK_DEADLINE_SECONDS = 180
DEFAULT_MAX_CONCURRENT_TASKS = 4


class ConfigError(ValueError):
    """Raised when the environment does not provide a usable configuration."""


def _require_http_url(value: str, name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute http(s) URL, got {value!r}")
    return value


def _parse_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _describe_errors(exc: ValidationError) -> str:
    details = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "configuration"
        details.append(f"{location}: {error['msg']}")
    return "; ".join(details)


class WorkflowLimits(BaseModel):
    """Bounded-workflow limits; enforced once the search loop exists."""

    model_config = ConfigDict(frozen=True)

    max_rounds: int = Field(default=DEFAULT_MAX_ROUNDS, ge=1)
    upstream_timeout_seconds: int = Field(default=DEFAULT_UPSTREAM_TIMEOUT_SECONDS, ge=1)
    task_deadline_seconds: int = Field(default=DEFAULT_TASK_DEADLINE_SECONDS, ge=1)
    max_concurrent_tasks: int = Field(default=DEFAULT_MAX_CONCURRENT_TASKS, ge=1)

    @model_validator(mode="after")
    def _timeout_fits_deadline(self) -> Self:
        if self.upstream_timeout_seconds > self.task_deadline_seconds:
            raise ValueError(
                "WORKFLOW_UPSTREAM_TIMEOUT_SECONDS must not exceed "
                "WORKFLOW_TASK_DEADLINE_SECONDS"
            )
        return self


class Settings(BaseModel):
    """Environment-backed service configuration."""

    model_config = ConfigDict(frozen=True)

    host: str = DEFAULT_HOST
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535)
    public_url: str = ""
    lcore_agent_card_url: str = DEFAULT_LCORE_AGENT_CARD_URL
    workflow: WorkflowLimits = Field(default_factory=WorkflowLimits)

    @field_validator("public_url")
    @classmethod
    def _normalize_public_url(cls, value: str) -> str:
        return _require_http_url(value.rstrip("/"), "PUBLIC_URL")

    @field_validator("lcore_agent_card_url")
    @classmethod
    def _validate_lcore_agent_card_url(cls, value: str) -> str:
        return _require_http_url(value, "LCORE_AGENT_CARD_URL")

    @property
    def rpc_url(self) -> str:
        return f"{self.public_url}/a2a"

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        host: str | None = None,
        port: int | None = None,
    ) -> Self:
        source = os.environ if env is None else env
        resolved_host = host or source.get("HOST") or DEFAULT_HOST
        resolved_port = (
            port if port is not None else _parse_int(source, "PORT", DEFAULT_PORT)
        )
        public_url = source.get("PUBLIC_URL") or f"http://{resolved_host}:{resolved_port}"
        try:
            workflow = WorkflowLimits(
                max_rounds=_parse_int(
                    source, "WORKFLOW_MAX_ROUNDS", DEFAULT_MAX_ROUNDS
                ),
                upstream_timeout_seconds=_parse_int(
                    source,
                    "WORKFLOW_UPSTREAM_TIMEOUT_SECONDS",
                    DEFAULT_UPSTREAM_TIMEOUT_SECONDS,
                ),
                task_deadline_seconds=_parse_int(
                    source,
                    "WORKFLOW_TASK_DEADLINE_SECONDS",
                    DEFAULT_TASK_DEADLINE_SECONDS,
                ),
                max_concurrent_tasks=_parse_int(
                    source,
                    "WORKFLOW_MAX_CONCURRENT_TASKS",
                    DEFAULT_MAX_CONCURRENT_TASKS,
                ),
            )
            return cls(
                host=resolved_host,
                port=resolved_port,
                public_url=public_url,
                lcore_agent_card_url=source.get("LCORE_AGENT_CARD_URL")
                or DEFAULT_LCORE_AGENT_CARD_URL,
                workflow=workflow,
            )
        except ValidationError as exc:
            raise ConfigError(_describe_errors(exc)) from exc
