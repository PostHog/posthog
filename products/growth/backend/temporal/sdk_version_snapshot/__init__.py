from products.growth.backend.temporal.sdk_version_snapshot.workflow import (
    SdkVersionSnapshotWorkflow,
    snapshot_sdk_versions_activity,
)

WORKFLOWS = [SdkVersionSnapshotWorkflow]
ACTIVITIES = [snapshot_sdk_versions_activity]
