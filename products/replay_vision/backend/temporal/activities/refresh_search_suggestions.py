from django.core.cache import cache
from django.utils import timezone

from temporalio import activity

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.search_suggestions import (
    SuggestionError,
    refresh_scanner_suggestions,
    stale_suggestion_candidates,
)
from products.replay_vision.backend.temporal.constants import (
    SEARCH_SUGGESTIONS_MAX_PER_DAY,
    SEARCH_SUGGESTIONS_MAX_PER_RUN,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.search_suggestions_types import RefreshScannerSuggestionsInputs

# Per-day model-call counter across every run, the backstop against a bug that makes every scanner look stale.
_BUDGET_TTL_S = 2 * 24 * 3600


def _budget_key() -> str:
    return f"replay_vision:search_suggestions:budget:{timezone.now():%Y-%m-%d}"


def calls_made_today() -> int:
    return int(cache.get(_budget_key()) or 0)


def _count_call() -> None:
    key = _budget_key()
    cache.add(key, 0, timeout=_BUDGET_TTL_S)
    cache.incr(key)


@activity.defn
@track_activity()
def list_stale_search_suggestions_activity() -> list[RefreshScannerSuggestionsInputs]:
    """Scanners due a refresh this run, cut to whatever the daily budget still allows."""
    remaining = SEARCH_SUGGESTIONS_MAX_PER_DAY - calls_made_today()
    if remaining <= 0:
        return []
    rows = stale_suggestion_candidates(min(SEARCH_SUGGESTIONS_MAX_PER_RUN, remaining)).values_list("id", "team_id")
    return [RefreshScannerSuggestionsInputs(scanner_id=scanner_id, team_id=team_id) for scanner_id, team_id in rows]


@activity.defn
@track_activity()
def refresh_scanner_search_suggestions_activity(inputs: RefreshScannerSuggestionsInputs) -> bool:
    """Regenerate one scanner's phrases. False when the scanner is gone or the model gave nothing usable."""
    scanner = ReplayScanner.objects.filter(team_id=inputs.team_id, id=inputs.scanner_id).first()
    if scanner is None:
        return False
    _count_call()
    try:
        refresh_scanner_suggestions(scanner)
    except SuggestionError:
        # Already logged with detail; the stored phrases stay and the next run retries after the interval.
        ReplayScanner.objects.filter(pk=scanner.pk).update(search_suggestions_generated_at=timezone.now())
        return False
    return True
