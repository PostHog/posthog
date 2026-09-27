from django.utils import timezone

from temporalio import activity

from posthog.models.team import Team

from products.replay_vision.backend.consent import is_ai_data_processing_approved
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.models.team_replay_vision_config import TeamReplayVisionConfig
from products.replay_vision.backend.search_suggestions import (
    SuggestionError,
    model_calls_today,
    refresh_scanner_suggestions,
    refresh_team_suggestions,
    stale_suggestion_candidates,
    stale_team_candidates,
)
from products.replay_vision.backend.temporal.constants import (
    SEARCH_SUGGESTIONS_MAX_PER_DAY,
    SEARCH_SUGGESTIONS_MAX_PER_RUN,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.search_suggestions_types import RefreshScannerSuggestionsInputs


@activity.defn
@track_activity()
def list_stale_search_suggestions_activity() -> list[RefreshScannerSuggestionsInputs]:
    """Teams and scanners due a look this run, cut to whatever the daily model-call budget still allows. Teams
    come first because their phrases fill the cross-scanner view most people land on."""
    remaining = min(SEARCH_SUGGESTIONS_MAX_PER_RUN, SEARCH_SUGGESTIONS_MAX_PER_DAY - model_calls_today())
    if remaining <= 0:
        return []
    teams = [RefreshScannerSuggestionsInputs(team_id=team_id) for team_id in stale_team_candidates(remaining // 4)]
    rows = stale_suggestion_candidates(remaining - len(teams)).values_list("id", "team_id")
    return teams + [RefreshScannerSuggestionsInputs(scanner_id=sid, team_id=team_id) for sid, team_id in rows]


@activity.defn
@track_activity()
def refresh_scanner_search_suggestions_activity(inputs: RefreshScannerSuggestionsInputs) -> bool:
    """Regenerate one scanner's phrases, or the team's cross-scanner phrases when no scanner is named. False
    when nothing was regenerated: the scope is gone, consent was withdrawn since listing, too few new
    observations, or no phrase the model gave finds anything."""
    if inputs.scanner_id is None:
        return _refresh_team(inputs.team_id)
    scanner = (
        ReplayScanner.objects.filter(team_id=inputs.team_id, id=inputs.scanner_id)
        .only(
            "id",
            "team_id",
            "name",
            "scanner_type",
            "scanner_config",
            "search_suggestions",
            "search_suggestions_watermark",
            "experiment_targeting",
        )
        .first()
    )
    if scanner is None or not is_ai_data_processing_approved(inputs.team_id):
        return False
    try:
        return refresh_scanner_suggestions(scanner)
    except Exception as e:
        # Stamp on any failure so the scanner waits an interval instead of retrying at the head of every run.
        ReplayScanner.objects.filter(pk=scanner.pk).update(search_suggestions_generated_at=timezone.now())
        if isinstance(e, SuggestionError):
            # Already logged with detail; the stored phrases stay.
            return False
        raise


def _refresh_team(team_id: int) -> bool:
    team = Team.objects.filter(id=team_id).first()
    if team is None or not is_ai_data_processing_approved(team_id):
        return False
    try:
        return refresh_team_suggestions(team)
    except Exception as e:
        # Same back-off as a scanner: stamp so the team waits instead of retrying at the head of every run.
        TeamReplayVisionConfig.objects.filter(pk=team_id).update(search_suggestions_generated_at=timezone.now())
        if isinstance(e, SuggestionError):
            return False
        raise
