import temporalio.activity

from posthog.sync import database_sync_to_async

from products.experiments.backend.temporal.enrollment_census_logic import run_enrollment_census_sync
from products.experiments.backend.temporal.models import ExperimentPrecomputeEnrollmentCensusInputs


@temporalio.activity.defn
async def run_experiment_enrollment_census(inputs: ExperimentPrecomputeEnrollmentCensusInputs) -> dict:
    """Run the census and log the report; returns counts for the workflow result."""

    def _run() -> dict:
        report = run_enrollment_census_sync(window_days=inputs.window_days)
        return {
            "evaluated_teams": report.evaluated_teams,
            "candidates": len(report.candidates),
            "excluded": len(report.excluded),
        }

    return await database_sync_to_async(_run)()
