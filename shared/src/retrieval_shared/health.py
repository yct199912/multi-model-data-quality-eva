"""Unified health check response model for all services.

Provides a consistent /health endpoint format across all microservices
with version, uptime, and optional dependency status.

Usage:
    from retrieval_shared.health import create_health_endpoint

    # In service main.py:
    create_health_endpoint(app, service_name="auth-service", version="1.0.0")
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel


class DependencyStatus(BaseModel):
    status: Literal["up", "down"]
    latency_ms: int
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["up", "down", "starting", "degraded"]
    service: str
    version: str
    started_at: datetime
    uptime_seconds: int
    dependencies: dict[str, DependencyStatus] | None = None


def create_health_endpoint(
    app: FastAPI,
    service_name: str,
    version: str = "1.0.0",
    dependency_checkers: dict[str, Any] | None = None,
) -> None:
    """Register a unified /health endpoint on the FastAPI app.

    Args:
        app: The FastAPI application.
        service_name: Name of the service (e.g., "auth-service").
        version: Service version string.
        dependency_checkers: Optional dict of {name: async_checker_fn} for
            dependency health checks. Each checker should return DependencyStatus.
    """
    started_at = datetime.now(timezone.utc)
    start_time = time.monotonic()

    @app.get("/health", response_model=HealthResponse)
    async def health():
        uptime = int(time.monotonic() - start_time)
        deps: dict[str, DependencyStatus] | None = None
        overall_status: Literal["up", "down", "starting", "degraded"] = "up"

        if dependency_checkers:
            deps = {}
            for name, checker in dependency_checkers.items():
                try:
                    deps[name] = await checker()
                except Exception as e:
                    deps[name] = DependencyStatus(
                        status="down", latency_ms=0, error=str(e)
                    )

            down_count = sum(1 for d in deps.values() if d.status == "down")
            if down_count == len(deps):
                overall_status = "down"
            elif down_count > 0:
                overall_status = "degraded"

        return HealthResponse(
            status=overall_status,
            service=service_name,
            version=version,
            started_at=started_at,
            uptime_seconds=uptime,
            dependencies=deps,
        )
