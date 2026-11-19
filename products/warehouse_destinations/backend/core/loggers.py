"""Loggers for destination code."""

import structlog


def get_write_only_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    """A logger that writes to stdout and produces nowhere else.

    Matches `posthog.temporal.common.logger.get_write_only_logger`, which this module does not
    import because that module loads Kafka and Django on import.
    """
    return structlog.get_logger(name, True, False)
