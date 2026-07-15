"""Mirror the Replay Vision Temporal pipeline's logs into the PostHog Logs product (dogfooding).

The pipeline logs through structlog on the `products.replay_vision.backend.temporal` namespace.
Attaching an `OtelLogHandler` there ships those records into Logs under `service.name = replay-vision`
with zero new log call sites, alongside the existing console/JSON output. A no-op until
OTLP_LOGS_INGEST_* are configured, so it is safe to install unconditionally at worker import.
"""

import logging

from posthog.otel_logs import OtelLogHandler

VISION_LOGS_SERVICE_NAME = "replay-vision"

# The namespace every Replay Vision Temporal logger falls under; records propagate to a handler here.
_TEMPORAL_LOGGER_NAME = "products.replay_vision.backend.temporal"

_installed = False


def install_vision_log_bridge() -> None:
    """Attach the OTLP log handler to the Replay Vision Temporal logger. Idempotent and cheap."""
    global _installed
    if _installed:
        return
    logger = logging.getLogger(_TEMPORAL_LOGGER_NAME)
    if not any(isinstance(handler, OtelLogHandler) for handler in logger.handlers):
        logger.addHandler(OtelLogHandler(VISION_LOGS_SERVICE_NAME))
    _installed = True
