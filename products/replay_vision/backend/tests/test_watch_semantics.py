from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

import numpy as np
from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.replay_vision.backend.models.replay_observation import ObservationTrigger, ReplayObservation
from products.replay_vision.backend.models.replay_observation_anchor_similarity import ReplayObservationAnchorSimilarity
from products.replay_vision.backend.models.replay_scanner import PromptValence, ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.replay_scanner_semantics import (
    ReplayScannerFeedGroup,
    ReplayScannerSearchTheme,
    ReplayScannerSemanticCenter,
)
from products.replay_vision.backend.semantic_space import SEMANTIC_DIMENSIONS, pack, semantic_vector
from products.replay_vision.backend.tests.helpers import axis_anchors, snapshot_for
from products.replay_vision.backend.watch_feed_groups import feed_group_cache
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION
from products.replay_vision.backend.watch_semantics import assign_semantics
from products.replay_vision.backend.watch_semantics_backfill import backfill_team_semantics
from products.replay_vision.backend.watch_themes import belongs_in_theme, finalize_label, name_theme

_THEMES = "products.replay_vision.backend.watch_themes"
_BACKFILL = "products.replay_vision.backend.watch_semantics_backfill"


def _rank(category: str = "failure") -> dict[str, Any]:
    return {"category": category, "contrast": 0.2, "anchor_version": ANCHOR_VERSION, "duplicate_of": "retired"}


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


class TestAssignSemantics(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        feed_group_cache.clear()
        self.scanner = self._scanner(ScannerType.SUMMARIZER)

    def _scanner(self, scanner_type: str, valence: str = "", name: str = "checkout") -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=self.team,
            name=name,
            scanner_type=scanner_type,
            prompt_valence=valence,
            scanner_config={"prompt": "What happened at checkout?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )

    def _observation(
        self, category: str = "failure", output: dict[str, Any] | None = None, scanner: ReplayScanner | None = None
    ) -> ReplayObservation:
        scanner = scanner or self.scanner
        return ReplayObservation.objects.create(
            scanner=scanner,
            team=self.team,
            session_id=f"sess-{ReplayObservation.objects.count()}",
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_snapshot=snapshot_for(scanner),
            watch_rank=_rank(category),
            scanner_result={"model_output": output or {"scanner_type": "summarizer", "summary": ""}},
        )

    def _assign(self, observation: ReplayObservation, vector: list[float]) -> Any:
        return assign_semantics(
            team_id=self.team.id,
            scanner_id=str(observation.scanner_id),
            observation_id=str(observation.id),
            vector=vector,
            now=timezone.now(),
        )

    def _counts(self, model: type[ReplayScannerFeedGroup] | type[ReplayScannerSearchTheme]) -> list[int]:
        return sorted(model.objects.for_team(self.team.id).values_list("member_count", flat=True))

    def test_close_observations_share_a_group_and_a_theme_and_a_redelivery_counts_once(self) -> None:
        first, close, far = self._observation(), self._observation(), self._observation()
        routine = self._observation(category="routine")

        joined = [self._assign(first, _vector(1.0)), self._assign(close, _vector(1.0, 0.1))]
        assert joined[0].group_id == joined[1].group_id
        assert joined[0].theme.theme_id == joined[1].theme.theme_id
        assert self._assign(first, _vector(1.0)) is None
        assert self._assign(far, _vector(0.0, 1.0)).group_id != joined[0].group_id
        # A routine row joins a feed group, so a viewer who counts it as an issue finds it grouped, but never a theme.
        routine_assignment = self._assign(routine, _vector(1.0))
        assert routine_assignment.group_id == joined[0].group_id
        assert routine_assignment.theme is None

        assert self._counts(ReplayScannerFeedGroup) == [1, 3]
        assert self._counts(ReplayScannerSearchTheme) == [1, 2]
        first.refresh_from_db()
        assert first.watch_rank is not None
        assert first.watch_rank["group"] == str(joined[0].group_id)
        assert first.watch_rank["theme"] == str(joined[0].theme.theme_id)
        assert "duplicate_of" not in first.watch_rank

    @parameterized.expand(
        [
            ("monitor_answer_the_scanner_is_not_looking_for", "unwanted_answer"),
            # A theme name reaches every scanner reader, so a row only the experiment's viewers may read stays out.
            ("observation_scanned_under_experiment_targeting", "experiment"),
            # The current valence may describe a question of the opposite sense to the one this row answered.
            ("monitor_row_scanned_under_an_earlier_prompt", "earlier_prompt"),
        ]
    )
    def test_some_rows_get_a_feed_group_but_no_theme(self, _name: str, case: str) -> None:
        if case == "experiment":
            observation = self._observation()
            snapshot = {**observation.scanner_snapshot, "experiment_targeting": {"experiment_id": 7}}
            ReplayObservation.objects.filter(id=observation.id).update(scanner_snapshot=snapshot)
        else:
            monitor = self._scanner(ScannerType.MONITOR, PromptValence.BAD, name="checkout errors")
            verdict = "no" if case == "unwanted_answer" else "yes"
            observation = self._observation(output={"scanner_type": "monitor", "verdict": verdict}, scanner=monitor)
            if case == "earlier_prompt":
                monitor.scanner_config = {"prompt": "Did checkout succeed?"}
                monitor.save(update_fields=["scanner_config"])

        assignment = self._assign(observation, _vector(1.0))

        assert assignment.theme is None
        observation.refresh_from_db()
        assert observation.watch_rank is not None
        assert observation.watch_rank["group"] == str(assignment.group_id)
        assert "theme" not in observation.watch_rank

    @parameterized.expand(
        [
            # A young scanner's mean is its own few rows, so two near-identical rows share both clusters on raw vectors.
            ("young_scanner_matches_raw", 0, 1),
            # Once the scanner's shared wording is taken out, what tells the rows apart decides.
            ("seasoned_scanner_matches_centred", 100, 2),
        ]
    )
    def test_the_scanner_mean_is_taken_out_once_it_is_known(self, _name: str, history: int, clusters: int) -> None:
        shared = np.zeros(SEMANTIC_DIMENSIONS, dtype=np.float32)
        shared[0] = history
        ReplayScannerSemanticCenter.objects.for_team(self.team.id).create(
            scanner=self.scanner, team=self.team, vector_sum=shared.tobytes(), member_count=history
        )
        self._assign(self._observation(), _vector(1.0, 0.2))
        self._assign(self._observation(), _vector(1.0, -0.2))
        assert len(self._counts(ReplayScannerFeedGroup)) == clusters
        assert len(self._counts(ReplayScannerSearchTheme)) == clusters

    def test_a_group_written_by_another_process_is_joined_rather_than_duplicated(self) -> None:
        self._assign(self._observation(), _vector(1.0))
        ReplayScannerFeedGroup.objects.for_team(self.team.id).create(
            team=self.team,
            scanner=self.scanner,
            vector_sum=pack(semantic_vector(_vector(0.0, 1.0))),
            member_count=1,
            last_member_at=timezone.now(),
        )
        center = ReplayScannerSemanticCenter.objects.for_team(self.team.id).get(scanner=self.scanner)
        center.member_count += 1
        center.save(update_fields=["member_count"])

        self._assign(self._observation(), _vector(0.0, 1.0))

        assert self._counts(ReplayScannerFeedGroup) == [1, 2]

    def test_the_backfill_fills_only_what_a_ranked_row_is_missing(self) -> None:
        grouped = self._observation()
        ReplayObservation.objects.filter(id=grouped.id).update(
            watch_rank={**_rank(), "group": "kept"}, status="succeeded", completed_at=timezone.now()
        )
        vector = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        with (
            patch(f"{_BACKFILL}._stored_vectors", return_value={str(grouped.id): vector}),
            patch(f"{_BACKFILL}.anchor_vectors", AsyncMock(return_value=axis_anchors())),
        ):
            backfill_team_semantics(self.team.id, timezone.now() - timedelta(days=1))

        grouped.refresh_from_db()
        assert grouped.watch_rank is not None
        assert grouped.watch_rank["group"] == "kept"
        assert set(grouped.watch_rank["scores"]) == {"failure", "struggle", "revenue", "routine"}
        assert (
            ReplayObservationAnchorSimilarity.objects.for_team(self.team.id)
            .filter(observation_id=grouped.id, anchor_version=ANCHOR_VERSION)
            .exists()
        )
        assert self._counts(ReplayScannerFeedGroup) == []

    def test_clusters_without_a_member_for_the_retention_window_are_pruned(self) -> None:
        stale = timezone.now() - timedelta(days=91)
        for model in (ReplayScannerFeedGroup, ReplayScannerSearchTheme):
            model.objects.for_team(self.team.id).create(
                team=self.team,
                scanner=self.scanner,
                vector_sum=pack(semantic_vector(_vector(0.0, 1.0))),
                member_count=3,
                last_member_at=stale,
            )
        with patch("products.replay_vision.backend.watch_semantics._PRUNE_EVERY", 1):
            self._assign(self._observation(), _vector(1.0))

        assert self._counts(ReplayScannerFeedGroup) == [1]
        assert self._counts(ReplayScannerSearchTheme) == [1]

    def test_a_theme_is_due_a_name_at_its_fifth_member(self) -> None:
        due = [self._assign(self._observation(), _vector(1.0)).theme.name_due for _ in range(5)]
        assert due == [False, False, False, False, True]

    def test_naming_writes_the_label_once_per_doubling_and_retries_a_failed_call(self) -> None:
        for _ in range(5):
            assignment = self._assign(
                self._observation(output={"scanner_type": "summarizer", "summary": "The card form rejected a card."}),
                _vector(1.0),
            )
        theme_id = assignment.theme.theme_id
        response = MagicMock(text='{"query": "Valid Card Rejected At Checkout."}')
        client = MagicMock(aclose=AsyncMock())
        client.models.generate_content = AsyncMock(side_effect=[RuntimeError("model unavailable"), response])
        with (
            patch(f"{_THEMES}.replay_gemini_client", AsyncMock(return_value=client)),
            patch(f"{_THEMES}.is_ai_data_processing_approved", return_value=True),
        ):
            with self.assertRaises(RuntimeError):
                async_to_sync(name_theme)(self.team.id, theme_id, timezone.now())
            first = async_to_sync(name_theme)(self.team.id, theme_id, timezone.now())
            again = async_to_sync(name_theme)(self.team.id, theme_id, timezone.now())

        assert (first, again) == ("valid card rejected at checkout", None)
        assert client.models.generate_content.await_count == 2
        theme = ReplayScannerSearchTheme.objects.for_team(self.team.id).get(id=theme_id)
        assert (theme.name, theme.rename_at_member_count) == ("valid card rejected at checkout", 10)
