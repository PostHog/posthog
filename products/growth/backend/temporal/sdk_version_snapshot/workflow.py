import json
import dataclasses
from datetime import timedelta

import structlog
from temporalio import activity, common, workflow

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater

logger = structlog.get_logger()


@dataclasses.dataclass
class SdkVersionSnapshotInputs:
    pass


@dataclasses.dataclass
class SdkVersionSnapshotResult:
    organizations: int = 0
    customers: int = 0


@activity.defn(name="snapshot-sdk-versions")
async def snapshot_sdk_versions_activity(_inputs: SdkVersionSnapshotInputs) -> SdkVersionSnapshotResult:
    """Aggregate current SDK versions and write them onto org/customer group properties.

    The whole rollup runs inside this activity, so the all-teams intermediate never crosses
    the workflow boundary (and so can't hit Temporal's ~2 MiB payload limit). Only the small
    written-counts result is returned.
    """
    async with Heartbeater():
        # Imported lazily so workflow sandbox import doesn't pull in Django/ClickHouse.
        from products.growth.backend.sdk_version_snapshot import snapshot_sdk_versions_to_groups  # noqa: PLC0415

        written = await database_sync_to_async(snapshot_sdk_versions_to_groups, thread_sensitive=False)()
        return SdkVersionSnapshotResult(
            organizations=written["organizations"],
            customers=written["customers"],
        )


@workflow.defn(name="snapshot-sdk-versions")
class SdkVersionSnapshotWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SdkVersionSnapshotInputs:
        loaded = json.loads(inputs[0]) if inputs else {}
        return SdkVersionSnapshotInputs(**loaded)

    @workflow.run
    async def run(self, _inputs: SdkVersionSnapshotInputs) -> SdkVersionSnapshotResult:
        try:
            return await workflow.execute_activity(
                snapshot_sdk_versions_activity,
                SdkVersionSnapshotInputs(),
                start_to_close_timeout=timedelta(hours=1),
                retry_policy=common.RetryPolicy(maximum_attempts=3),
                heartbeat_timeout=timedelta(minutes=2),
            )
        except Exception as e:
            capture_exception(e)
            raise
