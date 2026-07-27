"""Trigger an on-demand run of the experiment precompute canary.

With ``--experiment-id`` the canary runs in forensics mode against that one experiment (all of its
funnel/mean/ratio metrics, optionally narrowed with ``--metric-uuid``), regardless of team precompute
config or experiment runtime. Without it, a regular quota-sampled run is started.

Manual runs post divergences to Slack (marked manual) but skip the Prometheus push, so they don't
distort the scheduled canary's health signal. Results are visible in the Temporal UI on the started
workflow, and divergences land in the structured error log.
"""

import asyncio
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import sync_connect

from products.experiments.backend.temporal.models import CANARY_WORKFLOW_NAME, ExperimentPrecomputeCanaryInputs


class Command(BaseCommand):
    help = "Trigger an on-demand experiment precompute canary run"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--experiment-id", type=int, help="Canary this experiment only (forensics mode)")
        parser.add_argument(
            "--metric-uuid",
            action="append",
            dest="metric_uuids",
            help="Restrict to specific metric uuid(s); repeatable. Requires --experiment-id.",
        )
        parser.add_argument(
            "--time-budget-seconds", type=int, default=3600, help="Stop starting new metrics after this long"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["metric_uuids"] and not options["experiment_id"]:
            self.stderr.write("--metric-uuid requires --experiment-id")
            return

        inputs = ExperimentPrecomputeCanaryInputs(
            experiment_id=options["experiment_id"],
            metric_uuids=options["metric_uuids"],
            time_budget_seconds=options["time_budget_seconds"],
            triggered_manually=True,
        )

        workflow_id = (
            f"experiment-precompute-canary-manual-{inputs.experiment_id}"
            if inputs.experiment_id is not None
            else "experiment-precompute-canary-manual"
        )

        temporal = sync_connect()
        try:
            handle = asyncio.run(
                temporal.start_workflow(
                    CANARY_WORKFLOW_NAME,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                )
            )
        except WorkflowAlreadyStartedError:
            self.stderr.write(f"A canary run with id {workflow_id} is already in progress")
            return
        self.stdout.write(f"Started workflow {handle.id} (run {handle.result_run_id}) on {settings.TEMPORAL_HOST}")
