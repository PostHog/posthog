from temporalio import activity
from temporalio.exceptions import ApplicationError

from products.replay_vision.backend import variant_synthesis
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.constants import SYNTHESIS_ERROR_TYPE
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.synthesis_types import (
    ExperimentSynthesisInputs,
    FailExperimentSynthesisInputs,
    RefreshExperimentSynthesisInputs,
    RefreshExperimentSynthesisOutput,
)


def _run_step(step: str, inputs: ExperimentSynthesisInputs) -> None:
    try:
        getattr(variant_synthesis, step)(inputs.synthesis_id, inputs.team_id)
    except variant_synthesis.SynthesisError as e:
        # The reason is the row's error: a retry of the same input fails the same way.
        raise ApplicationError(str(e), type=SYNTHESIS_ERROR_TYPE, non_retryable=True) from e


@activity.defn
@track_activity()
def propose_synthesis_themes_activity(inputs: ExperimentSynthesisInputs) -> None:
    _run_step("propose_themes", inputs)


@activity.defn
@track_activity()
def assign_synthesis_themes_activity(inputs: ExperimentSynthesisInputs) -> None:
    _run_step("assign_themes", inputs)


@activity.defn
@track_activity()
def write_synthesis_digests_activity(inputs: ExperimentSynthesisInputs) -> None:
    _run_step("write_digests", inputs)


@activity.defn
@track_activity()
def write_synthesis_differences_activity(inputs: ExperimentSynthesisInputs) -> None:
    _run_step("write_differences", inputs)


@activity.defn
@track_activity()
def fail_experiment_synthesis_activity(inputs: FailExperimentSynthesisInputs) -> None:
    variant_synthesis.fail_run(inputs.synthesis_id, inputs.team_id, inputs.error)


@activity.defn
@track_activity()
def refresh_experiment_synthesis_activity(inputs: RefreshExperimentSynthesisInputs) -> RefreshExperimentSynthesisOutput:
    """Claim a scheduled synthesis refresh when one is due, piggybacking on the scanner sweep."""
    scanner = ReplayScanner.objects.filter(pk=inputs.scanner_id, team_id=inputs.team_id).select_related("team").first()
    if scanner is None:
        return RefreshExperimentSynthesisOutput()
    claimed = variant_synthesis.claim_due_refresh(scanner)
    return RefreshExperimentSynthesisOutput(synthesis_id=claimed.id if claimed is not None else None)
