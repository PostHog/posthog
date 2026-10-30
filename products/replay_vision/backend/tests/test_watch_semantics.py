import uuid
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

import numpy as np
from asgiref.sync import async_to_sync, sync_to_async
from parameterized import parameterized

from products.replay_vision.backend.highlight_feed_groups import feed_group_cache
from products.replay_vision.backend.models.replay_observation import ObservationTrigger, ReplayObservation
from products.replay_vision.backend.models.replay_observation_anchor_similarity import ReplayObservationAnchorSimilarity
from products.replay_vision.backend.models.replay_observation_rank import ReplayObservationRank
from products.replay_vision.backend.models.replay_scanner import (
    PromptValence,
    ReplayScanner,
    ScannerModel,
    ScannerOrigin,
    ScannerType,
)
from products.replay_vision.backend.models.replay_scanner_semantics import (
    ReplayScannerFeedGroup,
    ReplayScannerSearchTheme,
    ReplayScannerSemanticCenter,
)
from products.replay_vision.backend.semantic_space import (
    SEMANTIC_DIMENSIONS,
    SemanticSpace,
    nearest_cluster,
    pack,
    scanner_space,
    semantic_vector,
    unit,
)
from products.replay_vision.backend.tests.helpers import axis_anchors, set_rank, snapshot_for
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION
from products.replay_vision.backend.watch_semantics import SemanticItem, assign_semantics, assign_semantics_batch
from products.replay_vision.backend.watch_semantics_backfill import backfill_team_semantics
from products.replay_vision.backend.watch_themes import belongs_in_theme, finalize_label, name_theme, naming_candidates

_THEMES = "products.replay_vision.backend.watch_themes"
_BACKFILL = "products.replay_vision.backend.watch_semantics_backfill"


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

    @parameterized.expand([("raw", False), ("centred", True)])
    def test_nearest_cluster_matches_comparing_every_centred_mean(self, _name: str, centring: bool) -> None:
        rng = np.random.default_rng(7)
        sums = rng.normal(size=(200, SEMANTIC_DIMENSIONS)).astype(np.float32)
        counts = rng.integers(1, 40, size=200).astype(np.float32)
        vector = unit(rng.normal(size=SEMANTIC_DIMENSIONS).astype(np.float32))
        mean = (
            unit(rng.normal(size=SEMANTIC_DIMENSIONS).astype(np.float32)) * 0.3 if centring else np.zeros_like(vector)
        )
        space = SemanticSpace(vector=vector, mean=mean, centring=centring)

        expected = int(np.argmax(unit(sums / counts[:, None] - mean) @ unit(vector - mean)))

        assert nearest_cluster(sums, counts, np.einsum("ij,ij->i", sums, sums), space, -1.0, -1.0) == expected

    def test_a_cluster_whose_mean_matches_the_scanner_mean_still_takes_its_own_vector(self) -> None:
        common, rare = np.eye(SEMANTIC_DIMENSIONS, dtype=np.float32)[:2]
        sums = np.stack([common * 10_000, rare])
        counts = np.array([10_000, 1], dtype=np.float32)
        space = scanner_space(common * 10_000 + rare, 10_001, common)

        assert nearest_cluster(sums, counts, np.einsum("ij,ij->i", sums, sums), space, 0.65, 0.90) == 0


class TestAssignSemantics(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        feed_group_cache.clear()
        self.scanner = self._scanner(ScannerType.SUMMARIZER)

    def _scanner(
        self, scanner_type: str, valence: str = "", name: str = "checkout", origin: str = ScannerOrigin.CONFIGURED
    ) -> ReplayScanner:
        inline = origin == ScannerOrigin.INLINE
        return ReplayScanner.all_origins.create(
            team=self.team,
            name="" if inline else name,
            origin=origin,
            inline_key=name if inline else "",
            scanner_type=scanner_type,
            prompt_valence=valence,
            scanner_config={"prompt": "What happened at checkout?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )

    def _observation(
        self, category: str = "failure", output: dict[str, Any] | None = None, scanner: ReplayScanner | None = None
    ) -> ReplayObservation:
        scanner = scanner or self.scanner
        observation = ReplayObservation.objects.create(
            scanner=scanner,
            team=self.team,
            session_id=f"sess-{ReplayObservation.objects.count()}",
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_snapshot=snapshot_for(scanner),
            scanner_result={"model_output": output or {"scanner_type": "summarizer", "summary": ""}},
        )
        set_rank(observation, category=category, contrast=0.2)
        return observation

    def _clusters(self, observation: ReplayObservation) -> tuple[Any, Any]:
        rank = ReplayObservationRank.objects.for_team(self.team.id).get(observation_id=observation.id)
        return rank.feed_group_id, rank.search_theme_id

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

    @parameterized.expand(
        [
            ("configured", ScannerOrigin.CONFIGURED, False),
            ("inline", ScannerOrigin.INLINE, False),
            # One chunk holds a group created earlier in the same chunk, so the result matches one call per row.
            ("one_batch", ScannerOrigin.CONFIGURED, True),
        ]
    )
    def test_close_observations_share_a_group_and_a_theme_and_a_redelivery_counts_once(
        self, _name: str, origin: str, batch: bool
    ) -> None:
        self.scanner = self._scanner(ScannerType.SUMMARIZER, name="refunds", origin=origin)
        first, close, far = self._observation(), self._observation(), self._observation()
        routine = self._observation(category="routine")
        vectors = [(first, _vector(1.0)), (close, _vector(1.0, 0.1)), (far, _vector(0.0, 1.0)), (routine, _vector(1.0))]

        if batch:
            assigned = assign_semantics_batch(
                team_id=self.team.id,
                scanner_id=str(self.scanner.id),
                items=[SemanticItem(observation_id=str(o.id), vector=v, now=timezone.now()) for o, v in vectors],
            )
            joined: list[Any] = [assigned[str(first.id)], assigned[str(close.id)]]
            far_assignment: Any = assigned[str(far.id)]
            routine_assignment: Any = assigned[str(routine.id)]
        else:
            joined = [self._assign(first, _vector(1.0)), self._assign(close, _vector(1.0, 0.1))]
            far_assignment = self._assign(far, _vector(0.0, 1.0))
            # A message may spell the id in another case, and the row must still be found.
            routine_assignment = assign_semantics(
                team_id=self.team.id,
                scanner_id=str(self.scanner.id),
                observation_id=str(routine.id).upper(),
                vector=_vector(1.0),
                now=timezone.now(),
            )
        assert joined[0].group_id == joined[1].group_id
        assert joined[0].theme.theme_id == joined[1].theme.theme_id
        assert self._assign(first, _vector(1.0)) is None
        assert far_assignment.group_id != joined[0].group_id
        # A routine row joins a feed group, so a viewer who counts it as an issue finds it grouped, but never a theme.
        assert routine_assignment.group_id == joined[0].group_id
        assert routine_assignment.theme is None

        assert self._counts(ReplayScannerFeedGroup) == [1, 3]
        assert self._counts(ReplayScannerSearchTheme) == [1, 2]
        assert self._clusters(first) == (joined[0].group_id, joined[0].theme.theme_id)

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
        assert self._clusters(observation) == (assignment.group_id, None)

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

    # An embedding stored long after its observation was created falls outside the slice's bounded read.
    @parameterized.expand([("embedded_on_time", False), ("embedded_late", True)])
    def test_the_backfill_fills_only_what_a_ranked_row_is_missing(self, _name: str, late: bool) -> None:
        grouped = self._observation()
        kept = uuid.uuid4()
        set_rank(grouped, group=kept)
        vector = np.array([1.0, 0.0, 0.0], dtype=np.float32)

        def stored(_team_id: int, ids: list[str], _since: Any, until: Any) -> dict[str, np.ndarray]:
            return {} if late and until is not None else dict.fromkeys(ids, vector)

        with (
            patch(f"{_BACKFILL}.stored_vectors_between", side_effect=stored),
            patch(f"{_BACKFILL}.anchor_vectors", AsyncMock(return_value=axis_anchors())),
        ):
            backfill_team_semantics(self.team.id, timezone.now() - timedelta(days=1))

        assert self._clusters(grouped)[0] == kept
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

    def test_only_themes_a_suggestion_can_show_are_due_a_name(self) -> None:
        def theme(member_count: int, rename_at: int) -> ReplayScannerSearchTheme:
            return ReplayScannerSearchTheme.objects.for_team(self.team.id).create(
                team=self.team,
                scanner=self.scanner,
                vector_sum=pack(semantic_vector(_vector(1.0))),
                member_count=member_count,
                rename_at_member_count=rename_at,
                last_member_at=timezone.now(),
            )

        # The eight largest fill every suggestion slot and are named already, so the due ninth never shows.
        for size in range(20, 28):
            theme(size, rename_at=size * 2)
        theme(10, rename_at=5)
        assert list(naming_candidates(self.team.id, timezone.now())) == []

        shown = theme(30, rename_at=5)
        assert list(naming_candidates(self.team.id, timezone.now())) == [shown]

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
            patch(f"{_THEMES}.replay_gemini_client", MagicMock(return_value=client)),
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

    def test_a_failed_naming_leaves_a_newer_claim_in_place(self) -> None:
        for _ in range(5):
            assignment = self._assign(
                self._observation(output={"scanner_type": "summarizer", "summary": "The card form rejected a card."}),
                _vector(1.0),
            )
        themes = ReplayScannerSearchTheme.objects.for_team(self.team.id).filter(id=assignment.theme.theme_id)

        async def doubled_then_failed(*_args: Any, **_kwargs: Any) -> None:
            await sync_to_async(themes.update)(member_count=10, rename_at_member_count=20)
            raise RuntimeError("model unavailable")

        client = MagicMock(aclose=AsyncMock())
        client.models.generate_content = AsyncMock(side_effect=doubled_then_failed)
        with (
            patch(f"{_THEMES}.replay_gemini_client", MagicMock(return_value=client)),
            patch(f"{_THEMES}.is_ai_data_processing_approved", return_value=True),
            self.assertRaises(RuntimeError),
        ):
            async_to_sync(name_theme)(self.team.id, assignment.theme.theme_id, timezone.now())

        assert themes.get().rename_at_member_count == 20
