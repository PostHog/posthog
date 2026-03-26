from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.hogbot.backend.models import HogbotRuntime


@dataclass
class PersistHogbotSnapshotInput:
    team_id: int
    snapshot_external_id: str


@activity.defn(name="hogbot_persist_snapshot")
@asyncify
def persist_hogbot_snapshot(input: PersistHogbotSnapshotInput) -> None:
    runtime, _ = HogbotRuntime.objects.get_or_create(team_id=input.team_id)
    runtime.latest_snapshot_external_id = input.snapshot_external_id
    runtime.save(update_fields=["latest_snapshot_external_id", "updated_at"])
