import pytest
from unittest.mock import patch

from temporalio.testing import ActivityEnvironment

from products.growth.backend.temporal.sdk_version_snapshot.workflow import (
    SdkVersionSnapshotInputs,
    SdkVersionSnapshotResult,
    snapshot_sdk_versions_activity,
)

MODULE = "products.growth.backend.sdk_version_snapshot"


@pytest.mark.asyncio
async def test_activity_maps_written_counts_to_result():
    with patch(f"{MODULE}.snapshot_sdk_versions_to_groups", return_value={"organizations": 3, "customers": 2}):
        result = await ActivityEnvironment().run(snapshot_sdk_versions_activity, SdkVersionSnapshotInputs())

    assert result == SdkVersionSnapshotResult(organizations=3, customers=2)


@pytest.mark.asyncio
async def test_activity_propagates_failure():
    with patch(f"{MODULE}.snapshot_sdk_versions_to_groups", side_effect=Exception("boom")):
        with pytest.raises(Exception, match="boom"):
            await ActivityEnvironment().run(snapshot_sdk_versions_activity, SdkVersionSnapshotInputs())
