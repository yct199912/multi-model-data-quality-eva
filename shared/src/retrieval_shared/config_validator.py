"""Configuration validator for service startup validation.

Validates required fields, secret strength, and URL formats before
services establish connections. Fail-fast on critical issues, warn
on non-critical connectivity issues.

Usage:
    from retrieval_shared.config_validator import validate_config

    # In service main.py lifespan:
    validate_config(settings, service_name="auth-service")
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ConfigValidationError(Exception):
    """Configuration validation failed, service should not start."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Config validation failed: {'; '.join(errors)}")


# Known weak JWT secrets (lowercase for comparison)
WEAK_SECRET_PATTERNS: list[str] = [
    "super_secret",
    "change-me",
    "password",
    "secret",
    "123456",
    "qwerty",
    "inspur2026",
    "your-jwt-secret",
    "jwt-secret",
    "my-secret",
    "default",
]


def calculate_shannon_entropy(text: str) -> float:
    """Calculate Shannon entropy of a string in bits per character."""
    if not text:
        return 0.0
    length = len(text)
    freq = Counter(text)
    return -sum(
        (count / length) * math.log2(count / length) for count in freq.values()
    )


def validate_jwt_strength(secret: str) -> list[str]:
    """Validate JWT secret strength. Returns list of error messages."""
    errors: list[str] = []

    # 1. Minimum length (32 chars = 256 bits)
    if len(secret) < 32:
        errors.append(
            f"JWT_SECRET too short ({len(secret)} chars, minimum 32 required)"
        )

    # 2. Shannon entropy check (>= 3.5 bits/char for reasonable randomness)
    if len(secret) >= 32:
        entropy = calculate_shannon_entropy(secret)
        if entropy < 3.5:
            errors.append(
                f"JWT_SECRET has insufficient entropy ({entropy:.2f} bits/char, "
                f"minimum 3.5 required). Use a cryptographically random value."
            )

    # 3. Known weak pattern blacklist
    secret_lower = secret.lower()
    for pattern in WEAK_SECRET_PATTERNS:
        if pattern in secret_lower:
            errors.append(
                f"JWT_SECRET contains known weak pattern '{pattern}'. "
                f"Use a cryptographically random value."
            )
            break  # One match is enough

    # 4. Excessive character repetition
    if len(secret) > 0:
        unique_ratio = len(set(secret)) / len(secret)
        if unique_ratio < 0.33:  # Less than 1/3 unique characters
            errors.append(
                f"JWT_SECRET has too many repeated characters "
                f"({len(set(secret))} unique out of {len(secret)}). "
                f"Use a more random value."
            )

    return errors


def validate_url_format(url: str, name: str) -> list[str]:
    """Basic URL format validation. Returns list of error messages."""
    errors: list[str] = []
    if not url:
        return errors

    if not re.match(r"^(http|https|redis|postgresql|postgresql\+asyncpg)://", url):
        errors.append(f"{name} has invalid URL format: '{url[:50]}...'")

    return errors


def validate_required_fields(
    settings: Any, required_fields: list[str]
) -> list[str]:
    """Check that required fields are non-empty. Returns list of error messages."""
    errors: list[str] = []
    for field_name in required_fields:
        value = getattr(settings, field_name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"Required field '{field_name}' is missing or empty")
    return errors


async def check_redis_connectivity(redis_url: str) -> str | None:
    """Check Redis connectivity. Returns warning message or None."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url, socket_connect_timeout=3)
        try:
            await client.ping()
            return None
        finally:
            await client.close()
    except Exception as e:
        return f"Redis connectivity check failed: {e}. Rate limiting may not work."


def validate_config(
    settings: Any,
    service_name: str,
    required_fields: list[str] | None = None,
    check_redis: bool = False,
    redis_url: str | None = None,
) -> None:
    """Validate service configuration. Raises ConfigValidationError on failure.

    Args:
        settings: The service's Settings instance.
        service_name: Name of the service for logging.
        required_fields: List of required field names to check.
        check_redis: Whether to check Redis connectivity (warn only).
        redis_url: Redis URL to check (if check_redis is True).

    Raises:
        ConfigValidationError: If critical validation fails.
    """
    all_errors: list[str] = []

    # Validate required fields
    if required_fields:
        all_errors.extend(validate_required_fields(settings, required_fields))

    # Validate JWT secret if present
    jwt_secret = getattr(settings, "jwt_secret", None)
    if jwt_secret:
        all_errors.extend(validate_jwt_strength(jwt_secret))

    # Validate URL formats
    url_fields = {
        "postgres_dsn": "POSTGRES_DSN",
        "redis_url": "REDIS_URL",
        "gitea_base_url": "GITEA_BASE_URL",
        "model_server_url": "MODEL_SERVER_URL",
    }
    for field_name, display_name in url_fields.items():
        value = getattr(settings, field_name, None)
        if value:
            all_errors.extend(validate_url_format(value, display_name))

    # Raise if critical errors found
    if all_errors:
        for error in all_errors:
            logger.error("config_validation_error", service=service_name, error=error)
        raise ConfigValidationError(all_errors)

    logger.info("config_validation_passed", service=service_name)

    # Non-critical: Redis connectivity check (warn only)
    if check_redis and redis_url:
        import asyncio

        async def _check() -> None:
            warning = await check_redis_connectivity(redis_url)
            if warning:
                logger.warning(
                    "redis_connectivity_warning",
                    service=service_name,
                    message=warning,
                )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_check())
        except RuntimeError:
            # No event loop running, skip async check
            pass
