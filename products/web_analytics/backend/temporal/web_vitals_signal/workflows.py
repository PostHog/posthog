"""
Temporal workflows for the web-vitals signal pipeline.

A single fan-out workflow per scheduled tick:
- Resolve opted-in teams (or use the explicit `team_ids` override for debug/test).
- For each team, run both evaluation activities sequentially under a shared concurrency
  semaphore to bound parallel query load on ClickHouse.
- Aggregate totals and return them so the schedule's run history shows useful counts.
"""

import json
import asyncio
import dataclasses
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.web_analytics.backend.temporal.web_vitals_signal.activities import (
        evaluate_team_regressions,
        evaluate_team_threshold_crossings,
        list_opted_in_web_vitals_teams,
    )
    from products.web_analytics.backend.temporal.web_vitals_signal.types import (
        WebVitalsEvaluationInput,
        WebVitalsFanOutInput,
    )


ACTIVITY_RETRY_POLICY = common.RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
)


@workflow.defn(name="web-vitals-signals")
class WebVitalsSignalsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> WebVitalsFanOutInput:
        if inputs:
            data = json.loads(inputs[0])
            return WebVitalsFanOutInput(
                **{f.name: data[f.name] for f in dataclasses.fields(WebVitalsFanOutInput) if f.name in data}
            )
        return WebVitalsFanOutInput()

    @workflow.run
    async def run(self, input: WebVitalsFanOutInput | None = None) -> dict:
        if input is None:
            input = WebVitalsFanOutInput()

        # workflow.now() is the Temporal-deterministic clock — same value on replay.
        now_iso = input.now_iso or workflow.now().isoformat()

        team_ids = input.team_ids
        if team_ids is None:
            team_ids = await workflow.execute_activity(
                list_opted_in_web_vitals_teams,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=ACTIVITY_RETRY_POLICY,
            )

        if not team_ids:
            workflow.logger.info("No teams opted in to web vitals signals")
            return {
                "teams_evaluated": 0,
                "signals_emitted": 0,
                "signals_dropped": 0,
                "failed_teams": 0,
            }

        semaphore = asyncio.Semaphore(max(1, input.max_concurrent))

        async def _run_team(team_id: int) -> tuple[int, int]:
            async with semaphore:
                eval_input = WebVitalsEvaluationInput(team_id=team_id, now_iso=now_iso)
                threshold = await workflow.execute_activity(
                    evaluate_team_threshold_crossings,
                    eval_input,
                    start_to_close_timeout=timedelta(minutes=10),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
                regression = await workflow.execute_activity(
                    evaluate_team_regressions,
                    eval_input,
                    start_to_close_timeout=timedelta(minutes=10),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
                return (
                    threshold.signals_emitted + regression.signals_emitted,
                    threshold.signals_dropped + regression.signals_dropped,
                )

        results = await asyncio.gather(
            *[_run_team(tid) for tid in team_ids],
            return_exceptions=True,
        )

        signals_emitted = 0
        signals_dropped = 0
        failed_teams = 0
        for team_id, result in zip(team_ids, results):
            if isinstance(result, BaseException):
                failed_teams += 1
                workflow.logger.error("web vitals signal team eval failed", team_id=team_id, error=str(result))
                continue
            emitted, dropped = result
            signals_emitted += emitted
            signals_dropped += dropped

        return {
            "teams_evaluated": len(team_ids) - failed_teams,
            "signals_emitted": signals_emitted,
            "signals_dropped": signals_dropped,
            "failed_teams": failed_teams,
        }
