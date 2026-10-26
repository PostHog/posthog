from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

import numpy as np
from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.replay_vision.backend.models.replay_observation import ObservationTrigger, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.replay_scanner_theme import ReplayScannerTheme, ReplayScannerThemeCenter
from products.replay_vision.backend.tests.helpers import snapshot_for
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION
from products.replay_vision.backend.watch_themes import (
    THEME_DIMENSIONS,
    assign_theme,
    belongs_in_theme,
    finalize_label,
    name_theme,
)

_THEMES = "products.replay_vision.backend.watch_themes"


def _rank(category: str = "failure") -> dict[str, Any]:
    return {"category": category, "contrast": 0.2, "duplicate_of": None, "anchor_version": ANCHOR_VERSION}


def _vector(*head: float) -> list[float]:
    vector = np.zeros(3072)
    vector[: len(head)] = head
    return (vector / np.linalg.norm(vector)).tolist()


class TestThemeRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("routine_never_themes", "routine", ScannerType.SUMMARIZER, "", {}, False),
            ("summarizer_issue_themes", "struggle", ScannerType.SUMMARIZER, "", {}, True),
            ("bad_news_monitor_keeps_yes", "failure", ScannerType.MONITOR, "bad", {"verdict": "yes"}, True),
            ("bad_news_monitor_drops_no", "failure", ScannerType.MONITOR, "bad", {"verdict": "no"}, False),
            ("good_news_monitor_keeps_no", "failure", ScannerType.MONITOR, "good", {"verdict": "no"}, True),
            ("unjudged_monitor_keeps_every_answer", "failure", ScannerType.MONITOR, "", {"verdict": "no"}, True),
        ]
    )
    def test_which_observations_join_a_theme(
        self, _name: str, category: str, scanner_type: str, valence: str, output: dict[str, Any], expected: bool
    ) -> None:
        assert (
            belongs_in_theme(category=category, scanner_type=scanner_type, valence=valence, output=output) is expected
        )

    @parameterized.expand(
        [
            ("normalised", "  Card Declined At Checkout. ", "card declined at checkout"),
            ("too_long", " ".join(["word"] * 11), ""),
            ("identifier", "errors for someone@example.com", ""),
            ("empty", "", ""),
        ]
    )
    def test_label_shape(self, _name: str, raw: str, expected: str) -> None:
        assert finalize_label(raw) == expected


class TestAssignTheme(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="checkout",
            scanner_type=ScannerType.SUMMARIZER,
            scanner_config={"prompt": "What happened at checkout?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )

    def _observation(self, category: str = "failure", reasoning: str = "") -> ReplayObservation:
        return ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=f"sess-{ReplayObservation.objects.count()}",
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_snapshot=snapshot_for(self.scanner),
            watch_rank=_rank(category),
            scanner_result={"model_output": {"scanner_type": "summarizer", "summary": reasoning}},
        )

    def _assign(self, observation: ReplayObservation, vector: list[float]) -> Any:
        return assign_theme(
            team_id=self.team.id,
            scanner_id=str(self.scanner.id),
            observation_id=str(observation.id),
            vector=vector,
            now=timezone.now(),
        )

    def test_close_observations_share_a_theme_and_a_redelivery_counts_once(self) -> None:
        first, close, far = self._observation(), self._observation(), self._observation()
        routine = self._observation(category="routine")

        joined = [self._assign(first, _vector(1.0)), self._assign(close, _vector(1.0, 0.1))]
        assert joined[0].theme_id == joined[1].theme_id
        assert self._assign(first, _vector(1.0)) is None
        assert self._assign(far, _vector(0.0, 1.0)).theme_id != joined[0].theme_id
        assert self._assign(routine, _vector(1.0)) is None

        counts = dict(ReplayScannerTheme.objects.for_team(self.team.id).values_list("id", "member_count"))
        assert counts == {joined[0].theme_id: 2, self._theme_of(far): 1}
        first.refresh_from_db()
        assert first.watch_rank is not None and first.watch_rank["theme"] == str(joined[0].theme_id)

    @parameterized.expand(
        [
            # A young scanner's mean is its own few rows, so two near-identical rows share a theme on raw vectors.
            ("young_scanner_matches_raw", 0, 1),
            # Once the scanner's shared wording is taken out, what tells the rows apart decides.
            ("seasoned_scanner_matches_centred", 100, 2),
        ]
    )
    def test_the_scanner_mean_is_taken_out_once_it_is_known(self, _name: str, history: int, themes: int) -> None:
        shared = np.zeros(THEME_DIMENSIONS, dtype=np.float32)
        shared[0] = history
        ReplayScannerThemeCenter.objects.for_team(self.team.id).create(
            scanner=self.scanner, team=self.team, vector_sum=shared.tobytes(), member_count=history
        )
        self._assign(self._observation(), _vector(1.0, 0.2))
        self._assign(self._observation(), _vector(1.0, -0.2))
        assert ReplayScannerTheme.objects.for_team(self.team.id).count() == themes

    def test_a_theme_is_due_a_name_at_its_fifth_member(self) -> None:
        due = [self._assign(self._observation(), _vector(1.0)).name_due for _ in range(5)]
        assert due == [False, False, False, False, True]

    def test_naming_writes_the_label_once_per_doubling(self) -> None:
        for _ in range(5):
            assignment = self._assign(self._observation(reasoning="The card form rejected a valid card."), _vector(1.0))
        response = MagicMock(text='{"query": "Valid Card Rejected At Checkout."}')
        client = MagicMock(aclose=AsyncMock())
        client.models.generate_content = AsyncMock(return_value=response)
        with (
            patch(f"{_THEMES}.replay_gemini_client", AsyncMock(return_value=client)),
            patch(f"{_THEMES}.is_ai_data_processing_approved", return_value=True),
        ):
            first = async_to_sync(name_theme)(self.team.id, assignment.theme_id, timezone.now())
            again = async_to_sync(name_theme)(self.team.id, assignment.theme_id, timezone.now())

        assert (first, again) == ("valid card rejected at checkout", None)
        assert client.models.generate_content.await_count == 1
        theme = ReplayScannerTheme.objects.for_team(self.team.id).get(id=assignment.theme_id)
        assert (theme.label, theme.name_at) == ("valid card rejected at checkout", 10)

    def _theme_of(self, observation: ReplayObservation) -> Any:
        observation.refresh_from_db()
        assert observation.watch_rank is not None
        return ReplayScannerTheme.objects.for_team(self.team.id).get(id=observation.watch_rank["theme"]).id
