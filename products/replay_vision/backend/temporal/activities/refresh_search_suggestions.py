from django.utils import timezone

from temporalio import activity

from products.replay_vision.backend.consent import is_ai_data_processing_approved
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.search_suggestions import (
    SuggestionError,
    model_calls_today,
    refresh_scanner_suggestions,
    stale_suggestion_candidates,
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
    """Scanners due a look this run, cut to whatever the daily model-call budget still allows."""
    remaining = SEARCH_SUGGESTIONS_MAX_PER_DAY - model_calls_today()
    if remaining <= 0:
        return []
    rows = stale_suggestion_candidates(min(SEARCH_SUGGESTIONS_MAX_PER_RUN, remaining)).values_list("id", "team_id")
    return [RefreshScannerSuggestionsInputs(scanner_id=scanner_id, team_id=team_id) for scanner_id, team_id in rows]


@activity.defn
@track_activity()
def refresh_scanner_search_suggestions_activity(inputs: RefreshScannerSuggestionsInputs) -> bool:
    """Regenerate one scanner's phrases. False when nothing was regenerated: the scanner is gone, consent was
    withdrawn since listing, too few new observations, or the model gave nothing usable."""
    scanner = (
        ReplayScanner.objects.filter(team_id=inputs.team_id, id=inputs.scanner_id)
        .only("id", "team_id", "search_suggestions", "search_suggestions_watermark")
        .first()
    )
    if scanner is None or not is_ai_data_processing_approved(inputs.team_id):
        return False
    try:
        return refresh_scanner_suggestions(scanner)
    except SuggestionError:
        # Already logged with detail. Stamp so the scanner waits an interval instead of retrying every run.
        ReplayScanner.objects.filter(pk=scanner.pk).update(search_suggestions_generated_at=timezone.now())
        return False
