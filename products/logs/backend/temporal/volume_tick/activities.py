import dataclasses
from datetime import UTC, datetime

import structlog
import temporalio.activity

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class VolumeTickInput:
    pass


@dataclasses.dataclass(frozen=True)
class VolumeTickOutput:
    ticked_at: str


@temporalio.activity.defn
async def volume_tick_heartbeat_activity(input: VolumeTickInput) -> VolumeTickOutput:
    # Scheduling skeleton for the log volume rollup: proves the every-minute
    # schedule fires end to end. No aggregation runs yet; the rollup writer
    # replaces this body.
    ticked_at = datetime.now(UTC).isoformat()
    logger.info("logs_volume_tick_heartbeat", ticked_at=ticked_at)
    return VolumeTickOutput(ticked_at=ticked_at)
