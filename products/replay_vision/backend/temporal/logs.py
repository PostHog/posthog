"""Mirror the Replay Vision Temporal pipeline's logs into the PostHog Logs product (dogfooding).

Attaching an `OtelLogHandler` to the `products.replay_vision.backend.temporal` namespace ships those
records into Logs under `service.name = replay-vision` with no new call sites. A no-op until
OTLP_LOGS_INGEST_* are configured, so it is safe to install at worker import.
"""

import logging

from posthog.otel_logs import OtelLogHandler

VISION_LOGS_SERVICE_NAME = "replay-vision"

# Every Replay Vision Temporal logger falls under this namespace, so a handler here catches them all.
_TEMPORAL_LOGGER_NAME = "products.replay_vision.backend.temporal"

# Fail-closed allowlist: only these operational fields ship to the shared Logs project. Anything else
# (previews, prompts, exception messages, payload-derived values) is dropped so no team's
# session-derived content crosses in.
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
