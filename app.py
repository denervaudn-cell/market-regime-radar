"""Deployable ASGI entry point: uv run uvicorn app:app."""

import structlog

from radar.app import create_app

structlog.configure(
	processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()]
)

app = create_app()
