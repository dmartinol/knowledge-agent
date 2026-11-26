"""Local entry point: ``uv run knowledge-agent``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import pydantic_ai
import uvicorn

from knowledge_agent.config import ConfigError, Settings
from knowledge_agent.server import create_app
from knowledge_agent.skills import SkillBundle, SkillError, load_skills

logger = logging.getLogger("knowledge_agent")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="knowledge-agent",
        description="Run the Knowledge Search A2A agent locally.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Bind address (default: $HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (default: $PORT or 8081)",
    )
    return parser.parse_args(argv)


def _log_startup(settings: Settings, skills: SkillBundle) -> None:
    logger.info(
        "Knowledge agent starting: model=%s provider=%s public_url=%s "
        "retriever=%s lcore_card=%s lcore_rest=%s",
        settings.llm.model,
        settings.llm.base_url,
        settings.public_url,
        settings.retriever.value,
        settings.lcore_agent_card_url,
        settings.lcore_rest_url,
    )
    logger.info("Skills loaded from %s: %s", settings.skills_dir, skills.summary)


def main(argv: list[str] | None = None) -> None:
    pydantic_ai.BANNER_ENABLED = False
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv)
    try:
        settings = Settings.from_env(host=args.host, port=args.port)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not settings.llm.configured:
        print(
            "configuration error: AGENT_LLM_BASE_URL, AGENT_LLM_MODEL, and "
            "AGENT_LLM_API_KEY must be set",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        skills = asyncio.run(load_skills(settings.skills_dir))
    except SkillError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _log_startup(settings, skills)
    uvicorn.run(
        create_app(settings, skills=skills),
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
