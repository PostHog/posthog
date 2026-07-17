"""Mirror the Replay Vision Temporal pipeline's logs into the PostHog Logs product (dogfooding).

The worker configures structlog with a non-stdlib logger factory, so we ship logs with a structlog
processor (not a stdlib handler). `build_vision_log_mirror()` returns that processor, wired for the
`products.replay_vision.backend.temporal` namespace under `service.name = replay-vision`. The worker
start command inserts it into the log chain for the Replay Vision task queue. A no-op until
OTLP_LOGS_INGEST_* are configured.
"""

from typing import TYPE_CHECKING

from posthog.otel_logs import otel_log_mirror_processor

if TYPE_CHECKING:
    import structlog

VISION_LOGS_SERVICE_NAME = "replay-vision"

# Every Replay Vision Temporal logger falls under this namespace, so mirroring it catches them all.
VISION_LOGS_LOGGER_PREFIX = "products.replay_vision.backend.temporal"

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


def build_vision_log_mirror() -> "structlog.types.Processor":
    return otel_log_mirror_processor(
        VISION_LOGS_SERVICE_NAME,
        logger_prefix=VISION_LOGS_LOGGER_PREFIX,
        attribute_allowlist=VISION_LOG_ATTRIBUTE_ALLOWLIST,
    )
