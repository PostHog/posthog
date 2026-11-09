"""Facade for the internal logs producer, which sends a team's own internal logs to that team's logs product."""

from products.logs.backend.internal_logs_producer import (
    InternalLogEntry,
    InternalLogsProducer,
    InternalLogsProducerConfig,
)

__all__ = ["InternalLogEntry", "InternalLogsProducer", "InternalLogsProducerConfig"]
