import uuid
import logging
from datetime import timedelta

import pytest

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.exports.workflows import ExportAssetWorkflowInputs

from products.slack_app.backend.temporal.slack_app_unfurl_charts import SlackAppUnfurlChartsWorkflow
from products.slack_app.backend.temporal.types import (
    SlackAppUnfurlChartsPostInput,
    SlackAppUnfurlChartsPrepared,
    SlackAppUnfurlChartsWorkflowInputs,
    SlackUnfurlChartAsset,
)

_RENDERED_ASSET_ID = 2
_FAILING_ASSET_ID = 3

rendered_asset_ids: list[int] = []
posted: list[SlackAppUnfurlChartsPostInput] = []


@activity.defn(name="prepare_slack_unfurl_charts_activity")
async def _fake_prepare(inputs: SlackAppUnfurlChartsWorkflowInputs) -> SlackAppUnfurlChartsPrepared:
    return SlackAppUnfurlChartsPrepared(
        distinct_id="user-1",
        assets=[
            SlackUnfurlChartAsset(render_key=f"insight:{asset_id}", asset_id=asset_id)
            for asset_id in (_RENDERED_ASSET_ID, _FAILING_ASSET_ID)
        ],
    )


@activity.defn(name="post_slack_unfurl_charts_activity")
async def _fake_post(post: SlackAppUnfurlChartsPostInput) -> None:
    posted.append(post)


@workflow.defn(name="export-asset")
class _FakeExportAssetWorkflow:
    @workflow.run
    async def run(self, inputs: ExportAssetWorkflowInputs) -> None:
        rendered_asset_ids.append(inputs.exported_asset_id)
        if inputs.exported_asset_id == _FAILING_ASSET_ID:
            raise ApplicationError("render failed", non_retryable=True)


@pytest.mark.asyncio
async def test_a_failed_render_still_posts_the_other_charts(
    temporal_client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    rendered_asset_ids.clear()
    posted.clear()
    task_queue = f"test-unfurl-charts-{uuid.uuid4()}"
    inputs = SlackAppUnfurlChartsWorkflowInputs(
        team_id=1,
        integration_id=1,
        user_id=1,
        slack_user_id="U1",
        channel="C1",
        message_ts="123.456",
        unfurl_id=None,
        source=None,
        unfurls={},
        charts=[],
        export_task_queue=task_queue,
    )

    async with Worker(
        temporal_client,
        task_queue=task_queue,
        workflows=[SlackAppUnfurlChartsWorkflow, _FakeExportAssetWorkflow],
        activities=[_fake_prepare, _fake_post],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await temporal_client.execute_workflow(
            SlackAppUnfurlChartsWorkflow.run,
            inputs,
            id=f"test-unfurl-charts-{uuid.uuid4()}",
            task_queue=task_queue,
            execution_timeout=timedelta(seconds=30),
        )

    assert sorted(rendered_asset_ids) == [_RENDERED_ASSET_ID, _FAILING_ASSET_ID]
    assert len(posted) == 1
    assert [asset.asset_id for asset in posted[0].rendered] == [_RENDERED_ASSET_ID]
