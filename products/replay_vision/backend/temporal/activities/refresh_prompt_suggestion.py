from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.prompt_suggestions import refresh_prompt_suggestion_if_stale
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.sweep_types import RefreshPromptSuggestionInputs


@activity.defn
@close_db_connections
@track_activity()
def refresh_prompt_suggestion_activity(inputs: RefreshPromptSuggestionInputs) -> str:
    """Daily-gated prompt suggestion refresh, piggybacking on the scanner sweep: regenerates only when
    the rated set changed since the newest suggestion and that suggestion is at least a day old."""
    scanner = ReplayScanner.objects.filter(pk=inputs.scanner_id, team_id=inputs.team_id).first()
    if scanner is None:
        activity.logger.info(
            "refresh_prompt_suggestion: scanner no longer exists", extra={"scanner_id": str(inputs.scanner_id)}
        )
        return "missing_scanner"
    outcome = refresh_prompt_suggestion_if_stale(scanner)
    activity.logger.info(
        "refresh_prompt_suggestion",
        extra={"scanner_id": str(inputs.scanner_id), "outcome": outcome},
    )
    return outcome
