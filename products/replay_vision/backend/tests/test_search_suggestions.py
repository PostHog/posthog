from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.search_suggestions import (
    MAX_SUGGESTED_QUERIES,
    MIN_OBSERVATIONS_FOR_SUGGESTIONS,
    SuggestionError,
    _build_user_content,
    _finalize,
    _LlmQueries,
)
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


class TestSearchSuggestionsEndpoint(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.scanner = self._create_scanner(name="checkout", scanner_type=ScannerType.SUMMARIZER)

    @property
    def url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/observations/search_suggestions/"

    def _seed(self, count: int) -> None:
        for idx in range(count):
            ReplayObservation.objects.create(
                team=self.team,
                scanner=self.scanner,
                session_id=f"sess-{idx}",
                scanner_snapshot=snapshot_for(self.scanner),
                triggered_by=ObservationTrigger.SCHEDULE,
                status=ObservationStatus.SUCCEEDED,
                completed_at=timezone.now(),
                scanner_result={
                    "model_output": {"scanner_type": "summarizer", "title": "t", "summary": f"coupon failed {idx}"},
                    "signals_count": 0,
                },
            )

    @patch(_GENERATE_PATH)
    def test_too_few_observations_skip_the_model(self, mock_generate: MagicMock) -> None:
        self._seed(MIN_OBSERVATIONS_FOR_SUGGESTIONS - 1)
        resp = self.client.get(f"{self.url}?scanner_id={self.scanner.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["queries"], [])
        mock_generate.assert_not_called()

    @patch(_GENERATE_PATH)
    def test_suggestions_come_from_the_model_once_then_from_cache(self, mock_generate: MagicMock) -> None:
        self._seed(MIN_OBSERVATIONS_FOR_SUGGESTIONS)
        mock_generate.return_value = _LlmQueries(queries=["Coupon rejected at checkout"])
        for _ in range(2):
            resp = self.client.get(f"{self.url}?scanner_id={self.scanner.id}")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["queries"], ["coupon rejected at checkout"])
        mock_generate.assert_called_once()
        # The samples reach the model as fenced data.
        self.assertIn("<observations>", mock_generate.call_args.kwargs["user_content"])

    @patch(_GENERATE_PATH, side_effect=SuggestionError("model down"))
    def test_model_failure_is_an_empty_list(self, _mock: MagicMock) -> None:
        self._seed(MIN_OBSERVATIONS_FOR_SUGGESTIONS)
        resp = self.client.get(f"{self.url}?scanner_id={self.scanner.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["queries"], [])

    @patch("products.replay_vision.backend.api.observations.is_ai_data_processing_approved", return_value=False)
    @patch(_GENERATE_PATH)
    def test_consent_off_is_an_empty_list_not_an_error(self, mock_generate: MagicMock, _consent: MagicMock) -> None:
        self._seed(MIN_OBSERVATIONS_FOR_SUGGESTIONS)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["queries"], [])
        mock_generate.assert_not_called()
