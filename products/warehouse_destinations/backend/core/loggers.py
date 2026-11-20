"""Loggers for destination code."""

import structlog


def get_write_only_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    """Return the Temporal write-only logger, which writes to stdout and produces nowhere else.

    Call it when you log, not at import time: the logger module loads Kafka, Temporal and
    psycopg, and the facade and `core` must stay light to import.
    """
    from posthog.temporal.common.logger import get_write_only_logger as get_temporal_write_only_logger  # noqa: PLC0415

    return get_temporal_write_only_logger(name)
