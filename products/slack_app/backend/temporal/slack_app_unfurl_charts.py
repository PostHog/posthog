import json
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.exports.workflows import ExportAssetWorkflow, ExportAssetWorkflowInputs

from products.slack_app.backend.temporal.activities.unfurl_charts import (
    post_slack_unfurl_charts_activity,
    prepare_slack_unfurl_charts_activity,
)
from products.slack_app.backend.temporal.types import (
    SlackAppUnfurlChartsPostInput,
    SlackAppUnfurlChartsWorkflowInputs,
    SlackUnfurlChartAsset,
)

SLACK_APP_UNFURL_CHARTS_WORKFLOW_TIMEOUT = timedelta(minutes=5)
_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
# Nothing blocks on the unfurl, so the render gets room for an export retry instead of the 90s
# web-request cap. Deriving it from the budget keeps one prepare and one post attempt inside it.
_UNFURL_RENDER_TIMEOUT = SLACK_APP_UNFURL_CHARTS_WORKFLOW_TIMEOUT - 2 * _ACTIVITY_TIMEOUT


@workflow.defn(name="slack-app-unfurl-charts")
class SlackAppUnfurlChartsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SlackAppUnfurlChartsWorkflowInputs:
        return SlackAppUnfurlChartsWorkflowInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: SlackAppUnfurlChartsWorkflowInputs) -> None:
        prepared = await workflow.execute_activity(
            prepare_slack_unfurl_charts_activity,
            inputs,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
        results = await asyncio.gather(
            *(self._render(inputs, prepared.distinct_id, asset) for asset in prepared.assets),
            return_exceptions=True,
        )
        rendered = []
        for asset, result in zip(prepared.assets, results):
            if isinstance(result, BaseException):
                workflow.logger.warning(
                    "slack_app_unfurl_chart_render_failed",
                    extra={"asset_id": asset.asset_id, "error": str(result)},
                )
            else:
                rendered.append(asset)

        await workflow.execute_activity(
            post_slack_unfurl_charts_activity,
            SlackAppUnfurlChartsPostInput(
                request=inputs,
                rendered=rendered,
                elapsed_ms=int((workflow.now() - workflow.info().start_time).total_seconds() * 1000),
            ),
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )

    async def _render(
        self,
        inputs: SlackAppUnfurlChartsWorkflowInputs,
        distinct_id: str,
        asset: SlackUnfurlChartAsset,
    ) -> None:
        await workflow.execute_child_workflow(
            ExportAssetWorkflow.run,
            ExportAssetWorkflowInputs(
                exported_asset_id=asset.asset_id,
                team_id=inputs.team_id,
                distinct_id=distinct_id,
            ),
            id=f"export-asset-{asset.asset_id}",
            task_queue=inputs.export_task_queue,
            execution_timeout=_UNFURL_RENDER_TIMEOUT,
        )
