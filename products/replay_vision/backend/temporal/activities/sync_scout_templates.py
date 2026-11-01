import dataclasses

from temporalio import activity

from products.replay_vision.backend.scout_template_sync import sync_template_scouts
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.scout_template_sync_types import SyncScoutTemplatesResult


@activity.defn
@track_activity()
def sync_scout_templates_activity() -> SyncScoutTemplatesResult:
    result = sync_template_scouts()
    return SyncScoutTemplatesResult(**dataclasses.asdict(result))
