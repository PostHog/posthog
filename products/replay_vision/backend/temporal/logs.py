"""Mirror the Replay Vision Temporal pipeline's logs into the PostHog Logs product (dogfooding).

`build_vision_log_mirror()` returns the structlog processor the worker start command inserts into the
log chain for the Replay Vision task queue. A no-op until OTLP_LOGS_INGEST_* are configured.
"""

from typing import TYPE_CHECKING

from posthog.otel_logs import otel_log_mirror_processor

if TYPE_CHECKING:
    import structlog

VISION_LOGS_SERVICE_NAME = "replay-vision"
VISION_LOGS_LOGGER_PREFIX = "products.replay_vision.backend.temporal"

# Fail-closed: only these operational fields ship. Payload-derived values (previews, prompts,
# exception messages) are dropped so no team's session content crosses into the shared project.
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


def build_vision_log_mirror() -> "structlog.types.Processor":
    return otel_log_mirror_processor(
        VISION_LOGS_SERVICE_NAME,
        logger_prefix=VISION_LOGS_LOGGER_PREFIX,
        attribute_allowlist=VISION_LOG_ATTRIBUTE_ALLOWLIST,
    )
