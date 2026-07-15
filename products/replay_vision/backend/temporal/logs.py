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

# Operational fields safe to ship to the shared internal Logs project. The bridge is fail-closed:
# any log field not listed here (model output previews, prompts, exception messages, or other
# payload-derived values) is dropped, so no team's session-derived content crosses into the project.
VISION_LOG_ATTRIBUTE_ALLOWLIST = frozenset(
    {
        "observation_id",
        "scanner_id",
        "scanner_type",
        "vision_action_id",
        "schedule_id",
        "team_id",
        "session_id",
        "workflow_id",
        "gemini_file_name",
        "redis_key",
        "status",
        "kind",
        "attempt",
        "step",
        "count",
        "duration_ms",
        "model",
        "skipped_temporal_error",
    }
)

_installed = False


def install_vision_log_bridge() -> None:
    """Attach the OTLP log handler to the Replay Vision Temporal logger. Idempotent and cheap."""
    global _installed
    if _installed:
        return
    logger = logging.getLogger(_TEMPORAL_LOGGER_NAME)
    if not any(isinstance(handler, OtelLogHandler) for handler in logger.handlers):
        logger.addHandler(OtelLogHandler(VISION_LOGS_SERVICE_NAME, attribute_allowlist=VISION_LOG_ATTRIBUTE_ALLOWLIST))
    _installed = True
