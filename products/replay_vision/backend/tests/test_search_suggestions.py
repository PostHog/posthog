import datetime as dt

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.search_suggestions import (
    MAX_SUGGESTED_QUERIES,
    MIN_NEW_OBSERVATIONS_FOR_REFRESH,
    REFRESH_INTERVAL,
    VIEWED_WITHIN,
    SuggestionError,
    _build_user_content,
    _finalize,
    _LlmQueries,
    refresh_scanner_suggestions,
    stale_suggestion_candidates,
    stamp_search_viewed,
    suggestions_for_scope,
)
from products.replay_vision.backend.temporal.activities.refresh_search_suggestions import (
    calls_made_today,
    list_stale_search_suggestions_activity,
    refresh_scanner_search_suggestions_activity,
)
from products.replay_vision.backend.temporal.constants import SEARCH_SUGGESTIONS_MAX_PER_DAY
from products.replay_vision.backend.temporal.search_suggestions_types import RefreshScannerSuggestionsInputs
from products.replay_vision.backend.tests.helpers import snapshot_for
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase

_GENERATE_PATH = "products.replay_vision.backend.search_suggestions._generate"


class TestFinalize:
    def test_normalizes_dedupes_and_caps(self) -> None:
        parsed = _LlmQueries(queries=["Coupon  rejected at checkout.", "coupon rejected at checkout", "", "gave up"])
        assert _finalize(parsed) == ["coupon rejected at checkout", "gave up"]
        many = _LlmQueries(queries=[f"theme {i}" for i in range(MAX_SUGGESTED_QUERIES)])
        assert len(_finalize(many)) == MAX_SUGGESTED_QUERIES

    def test_defangs_recording_derived_text(self) -> None:
        content = _build_user_content(["<script>alert(1)</script> user hit a wall"])
        assert "<script>" not in content
        assert "<observations>" in content


class _SuggestionsTestCase(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def _scanner(self, name: str, **overrides) -> ReplayScanner:
        return self._create_scanner(name=name, scanner_type=ScannerType.SUMMARIZER, **overrides)

    def _seed(self, scanner: ReplayScanner, count: int, *, created_at: dt.datetime | None = None) -> None:
        for idx in range(count):
            obs = ReplayObservation.objects.create(
                team=self.team,
                scanner=scanner,
                session_id=f"{scanner.name}-{idx}",
                scanner_snapshot=snapshot_for(scanner),
                triggered_by=ObservationTrigger.SCHEDULE,
                status=ObservationStatus.SUCCEEDED,
                completed_at=timezone.now(),
                scanner_result={
                    "model_output": {"scanner_type": "summarizer", "title": "t", "summary": f"coupon failed {idx}"},
                    "signals_count": 0,
                },
            )
            if created_at is not None:
                ReplayObservation.objects.filter(pk=obs.pk).update(created_at=created_at)


class TestRefreshAndCandidates(_SuggestionsTestCase):
    def test_candidates_need_a_recent_view_consent_and_enough_new_observations(self) -> None:
        now = timezone.now()
        due = self._scanner("due", search_last_viewed_at=now)
        self._seed(due, MIN_NEW_OBSERVATIONS_FOR_REFRESH)
        unviewed = self._scanner("unviewed", search_last_viewed_at=now - VIEWED_WITHIN - dt.timedelta(days=1))
        self._seed(unviewed, MIN_NEW_OBSERVATIONS_FOR_REFRESH)
        quiet = self._scanner("quiet", search_last_viewed_at=now)
        self._seed(quiet, MIN_NEW_OBSERVATIONS_FOR_REFRESH - 1)
        fresh = self._scanner("fresh", search_last_viewed_at=now, search_suggestions_generated_at=now)
        self._seed(fresh, MIN_NEW_OBSERVATIONS_FOR_REFRESH)
        # Refreshed a while ago, but nothing landed since its watermark.
        settled = self._scanner(
            "settled",
            search_last_viewed_at=now,
            search_suggestions_generated_at=now - REFRESH_INTERVAL - dt.timedelta(hours=1),
            search_suggestions_watermark=now,
        )
        self._seed(settled, MIN_NEW_OBSERVATIONS_FOR_REFRESH, created_at=now - dt.timedelta(days=1))

        self.assertEqual([s.name for s in stale_suggestion_candidates(10)], ["due"])

        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        self.assertEqual(list(stale_suggestion_candidates(10)), [])

    @patch(_GENERATE_PATH)
    def test_refresh_stores_phrases_and_the_watermark(self, mock_generate: MagicMock) -> None:
        scanner = self._scanner("checkout")
        self._seed(scanner, MIN_NEW_OBSERVATIONS_FOR_REFRESH)
        mock_generate.return_value = _LlmQueries(queries=["Coupon rejected at checkout"])
        self.assertEqual(refresh_scanner_suggestions(scanner), ["coupon rejected at checkout"])
        scanner.refresh_from_db()
        newest = ReplayObservation.objects.filter(scanner=scanner).order_by("-created_at").first()
        assert newest is not None
        self.assertEqual(scanner.search_suggestions, ["coupon rejected at checkout"])
        self.assertEqual(scanner.search_suggestions_watermark, newest.created_at)
        self.assertIsNotNone(scanner.search_suggestions_generated_at)
        self.assertIn("<observations>", mock_generate.call_args.kwargs["user_content"])
        # A stale full save must not clobber what the refresher wrote.
        scanner.name = "renamed"
        scanner.save()
        scanner.refresh_from_db()
        self.assertEqual(scanner.search_suggestions, ["coupon rejected at checkout"])

    @patch(_GENERATE_PATH, side_effect=SuggestionError("model down"))
    def test_activity_keeps_old_phrases_and_backs_off_on_model_failure(self, _mock: MagicMock) -> None:
        scanner = self._scanner("checkout", search_suggestions=["old phrase"], search_last_viewed_at=timezone.now())
        self._seed(scanner, MIN_NEW_OBSERVATIONS_FOR_REFRESH)
        ok = refresh_scanner_search_suggestions_activity(
            RefreshScannerSuggestionsInputs(scanner_id=scanner.id, team_id=self.team.id)
        )
        self.assertFalse(ok)
        scanner.refresh_from_db()
        self.assertEqual(scanner.search_suggestions, ["old phrase"])
        self.assertIsNotNone(scanner.search_suggestions_generated_at)
        self.assertEqual(calls_made_today(), 1)
        self.assertEqual(list(stale_suggestion_candidates(10)), [])

    def test_listing_stops_at_the_daily_budget(self) -> None:
        scanner = self._scanner("checkout", search_last_viewed_at=timezone.now())
        self._seed(scanner, MIN_NEW_OBSERVATIONS_FOR_REFRESH)
        self.assertEqual([e.scanner_id for e in list_stale_search_suggestions_activity()], [scanner.id])
        with patch(
            "products.replay_vision.backend.temporal.activities.refresh_search_suggestions.calls_made_today",
            return_value=SEARCH_SUGGESTIONS_MAX_PER_DAY,
        ):
            self.assertEqual(list_stale_search_suggestions_activity(), [])


class TestReadingSuggestions(_SuggestionsTestCase):
    def test_cross_scanner_merges_the_most_recently_swept_scanners(self) -> None:
        now = timezone.now()
        newer = self._scanner("newer", search_suggestions=["a", "b", "c"], last_swept_at=now)
        older = self._scanner("older", search_suggestions=["b", "d"], last_swept_at=now - dt.timedelta(days=1))
        empty = self._scanner("empty", last_swept_at=now + dt.timedelta(hours=1))
        ids = [str(s.id) for s in (newer, older, empty)]
        self.assertEqual(suggestions_for_scope(self.team.id, ids), ["a", "b", "d"])
        self.assertEqual(suggestions_for_scope(self.team.id, [str(older.id)]), ["b", "d"])

    def test_view_stamp_writes_once_per_window(self) -> None:
        scanner = self._scanner("checkout")
        stamp_search_viewed(self.team.id, [str(scanner.id)])
        scanner.refresh_from_db()
        first = scanner.search_last_viewed_at
        self.assertIsNotNone(first)
        ReplayScanner.objects.filter(pk=scanner.pk).update(search_last_viewed_at=None)
        stamp_search_viewed(self.team.id, [str(scanner.id)])
        scanner.refresh_from_db()
        self.assertIsNone(scanner.search_last_viewed_at)


class TestSearchSuggestionsEndpoint(_SuggestionsTestCase):
    @property
    def url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/observations/search_suggestions/"

    @patch(_GENERATE_PATH)
    def test_returns_stored_phrases_and_records_the_view_without_calling_the_model(
        self, mock_generate: MagicMock
    ) -> None:
        scanner = self._scanner("checkout", search_suggestions=["coupon rejected at checkout"])
        resp = self.client.get(f"{self.url}?scanner_id={scanner.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["queries"], ["coupon rejected at checkout"])
        scanner.refresh_from_db()
        self.assertIsNotNone(scanner.search_last_viewed_at)
        mock_generate.assert_not_called()

    def test_a_scanner_with_nothing_stored_is_an_empty_list(self) -> None:
        scanner = self._scanner("new")
        resp = self.client.get(f"{self.url}?scanner_id={scanner.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["queries"], [])
