"""Activities for the prompt-suggestion evaluation workflow (test before apply).

Selection and comparison logic lives in `prompt_evaluation`; these activities wire it to the
suggestion row's `evaluation` JSON, which the Quality tab polls while the workflow runs.
"""

from typing import Any

from django.db import transaction
from django.utils import timezone

from temporalio import activity
from temporalio.exceptions import ApplicationError

from products.replay_vision.backend.models.replay_scanner_prompt_suggestion import (
    ReplayScannerPromptSuggestion,
    SuggestionStatus,
)
from products.replay_vision.backend.prompt_evaluation import (
    build_running_evaluation,
    classify_outcome,
    evaluation_supported,
    primary_outcome,
    select_evaluation_observations,
    summarize_results,
)
from products.replay_vision.backend.prompt_suggestions import labels_fingerprint
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.evaluation_types import (
    EvaluationSession,
    FinalizeEvaluationInputs,
    RecordEvaluationResultInputs,
    SelectEvaluationSessionsInputs,
    SelectEvaluationSessionsOutput,
)
from products.replay_vision.backend.temporal.types import ScannerSnapshot


def _get_suggestion(suggestion_id: Any, team_id: int) -> ReplayScannerPromptSuggestion:
    suggestion = (
        ReplayScannerPromptSuggestion.objects.filter(pk=suggestion_id, team_id=team_id)
        .select_related("scanner")
        .first()
    )
    if suggestion is None:
        raise ApplicationError(f"Prompt suggestion {suggestion_id} not found", non_retryable=True)
    return suggestion


@activity.defn
@track_activity()
def select_evaluation_sessions_activity(inputs: SelectEvaluationSessionsInputs) -> SelectEvaluationSessionsOutput:
    """Pick the rated sessions to test, build the suggested-config snapshot, and mark the evaluation running."""
    suggestion = _get_suggestion(inputs.suggestion_id, inputs.team_id)
    scanner = suggestion.scanner
    if not evaluation_supported(scanner):
        raise ApplicationError(f"Scanner type {scanner.scanner_type} does not support evaluation", non_retryable=True)
    if suggestion.status != SuggestionStatus.PENDING:
        raise ApplicationError(f"Suggestion is {suggestion.status}, not pending", non_retryable=True)

    observations = select_evaluation_observations(scanner)
    sessions = [
        EvaluationSession(
            observation_id=o.id,
            session_id=o.session_id,
            rated_correct=o.label.is_correct,  # type: ignore[attr-defined]
            before_outcome=primary_outcome((o.scanner_result or {}).get("model_output")),
        )
        for o in observations
    ]
    # The full proposed scanner_config drives the re-run, so tag-vocabulary changes are tested too.
    # Trigger changes (query, sampling_rate) pick sessions rather than shape per-session output, so
    # they don't participate. Suggestions predating parameter proposals swap the prompt only.
    suggested_config = ((suggestion.suggested_parameters or {}).get("scanner_config")) or {
        **(scanner.scanner_config or {}),
        "prompt": suggestion.suggested_prompt,
    }
    # Signals stay off so a dry run can't pollute the team's feeds.
    snapshot = ScannerSnapshot(
        name=scanner.name,
        scanner_type=scanner.scanner_type,
        scanner_version=scanner.scanner_version,
        model=scanner.model,
        provider=scanner.provider,
        emits_signals=False,
        scanner_config=suggested_config,
    )
    suggestion.evaluation = build_running_evaluation(
        total=len(sessions), labels_fingerprint=labels_fingerprint(scanner)
    )
    suggestion.save(update_fields=["evaluation"])
    return SelectEvaluationSessionsOutput(sessions=sessions, snapshot=snapshot)


@activity.defn
@track_activity()
def record_evaluation_result_activity(inputs: RecordEvaluationResultInputs) -> None:
    """Classify one session's fresh output against its rating and append it to the evaluation results."""
    after = primary_outcome(inputs.after_output) if inputs.after_output is not None else None
    outcome = classify_outcome(inputs.session.rated_correct, inputs.session.before_outcome, after)
    result = {
        "session_id": inputs.session.session_id,
        "observation_id": str(inputs.session.observation_id),
        "rated_correct": inputs.session.rated_correct,
        "before": inputs.session.before_outcome,
        "after": after,
        "outcome": outcome,
        "error": inputs.error,
    }
    # Sessions evaluate concurrently, so the append must be serialized on the row.
    with transaction.atomic():
        suggestion = (
            ReplayScannerPromptSuggestion.objects.select_for_update()
            .filter(pk=inputs.suggestion_id, team_id=inputs.team_id)
            .first()
        )
        if suggestion is None or not isinstance(suggestion.evaluation, dict):
            raise ApplicationError("Evaluation state missing for suggestion", non_retryable=True)
        results = [r for r in suggestion.evaluation.get("results", []) if r.get("session_id") != result["session_id"]]
        results.append(result)
        suggestion.evaluation = {**suggestion.evaluation, "results": results}
        suggestion.save(update_fields=["evaluation"])


@activity.defn
@track_activity()
def finalize_evaluation_activity(inputs: FinalizeEvaluationInputs) -> None:
    with transaction.atomic():
        suggestion = (
            ReplayScannerPromptSuggestion.objects.select_for_update()
            .filter(pk=inputs.suggestion_id, team_id=inputs.team_id)
            .first()
        )
        if suggestion is None or not isinstance(suggestion.evaluation, dict):
            return
        results = suggestion.evaluation.get("results", [])
        suggestion.evaluation = {
            **suggestion.evaluation,
            "status": "failed" if inputs.failed else "succeeded",
            "finished_at": timezone.now().isoformat(),
            "summary": summarize_results(results),
        }
        suggestion.save(update_fields=["evaluation"])
