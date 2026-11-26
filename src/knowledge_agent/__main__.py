"""Local entry point: ``uv run knowledge-agent``."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from knowledge_agent.config import ConfigError, Settings
from knowledge_agent.server import create_app


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


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    try:
        settings = Settings.from_env(host=args.host, port=args.port)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
