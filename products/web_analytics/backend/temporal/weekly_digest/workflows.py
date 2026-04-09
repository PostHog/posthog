import asyncio
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.web_analytics.backend.temporal.weekly_digest.activities import (
        build_and_send_wa_digest_for_org,
        get_orgs_for_wa_digest,
        send_test_wa_digest,
    )
    from products.web_analytics.backend.temporal.weekly_digest.types import (
        BuildAndSendDigestForOrgInput,
        SendTestDigestInput,
        WAWeeklyDigestInput,
    )


@workflow.defn(name="wa-weekly-digest")
class WAWeeklyDigestWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> WAWeeklyDigestInput:
        """Parse inputs from the management command CLI."""
        if inputs:
            import json
            import dataclasses

            data = json.loads(inputs[0])
            return WAWeeklyDigestInput(
                **{f.name: data[f.name] for f in dataclasses.fields(WAWeeklyDigestInput) if f.name in data}
            )
        return WAWeeklyDigestInput()

    @workflow.run
    async def run(self, input: WAWeeklyDigestInput) -> None:
        org_ids = await workflow.execute_activity(
            get_orgs_for_wa_digest,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=common.RetryPolicy(maximum_attempts=3),
        )

        if not org_ids:
            workflow.logger.info("No orgs targeted for WA weekly digest")
            return

        workflow.logger.info("Fanning out WA digest to %d orgs", len(org_ids))

        results = await asyncio.gather(
            *[
                workflow.execute_activity(
                    build_and_send_wa_digest_for_org,
                    BuildAndSendDigestForOrgInput(org_id=org_id, dry_run=input.dry_run),
                    start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=2),
                    ),
                )
                for org_id in org_ids
            ],
            return_exceptions=True,
        )

        successes = sum(1 for r in results if not isinstance(r, BaseException))
        failures = sum(1 for r in results if isinstance(r, BaseException))

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                workflow.logger.error(
                    "WA digest failed for org %s: %s",
                    org_ids[i],
                    str(result),
                )

        workflow.logger.info(
            "WA weekly digest complete: %d succeeded, %d failed",
            successes,
            failures,
        )


@workflow.defn(name="wa-weekly-digest-test")
class WAWeeklyDigestTestWorkflow(PostHogWorkflow):
    """Send a test digest email for a single team, bypassing feature flags."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SendTestDigestInput:
        """Parse inputs from the management command CLI.

        Usage: manage.py start_temporal_workflow wa-weekly-digest-test '{"team_id": 1, "email": "you@example.com"}'
        """
        import json

        data = json.loads(inputs[0])
        return SendTestDigestInput(
            team_id=data["team_id"],
            email=data["email"],
            force=data.get("force", False),
        )

    @workflow.run
    async def run(self, input: SendTestDigestInput) -> None:
        await workflow.execute_activity(
            send_test_wa_digest,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        )
