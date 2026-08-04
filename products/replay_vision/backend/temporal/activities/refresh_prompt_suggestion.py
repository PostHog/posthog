from temporalio import activity

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.prompt_suggestions import refresh_prompt_suggestion_if_stale
from products.replay_vision.backend.temporal.db_errors import is_transient_db_error
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import TransientDbError
from products.replay_vision.backend.temporal.sweep_types import RefreshPromptSuggestionInputs


@activity.defn
@track_activity()
def refresh_prompt_suggestion_activity(inputs: RefreshPromptSuggestionInputs) -> str:
    """Daily-gated prompt suggestion refresh, piggybacking on the scanner sweep: regenerates only when
    the rated set changed since the newest suggestion and that suggestion is at least a day old.

    The sweep workflow already treats this activity as best-effort (broad except, logged not paged),
    but the Temporal interceptor captures an exception before that handler ever sees it. A transient
    DB error is raised as non-reportable so it stops paging on a condition the workflow already tolerates.
    """
    try:
        scanner = ReplayScanner.objects.filter(pk=inputs.scanner_id, team_id=inputs.team_id).first()
        if scanner is None:
            activity.logger.info(
                "refresh_prompt_suggestion: scanner no longer exists", extra={"scanner_id": str(inputs.scanner_id)}
            )
            return "missing_scanner"
        outcome = refresh_prompt_suggestion_if_stale(scanner)
    except Exception as e:
        if is_transient_db_error(e):
            raise TransientDbError(str(e)) from e
        raise
    activity.logger.info(
        "refresh_prompt_suggestion",
        extra={"scanner_id": str(inputs.scanner_id), "outcome": outcome},
    )
    return outcome
