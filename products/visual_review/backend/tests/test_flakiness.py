"""Tests for the flakiness overview.

Coverage:
- A quarantine over a snapshot that still fails does not ask to be lifted.
- State turns on the share of window runs that failed, not on a count.
- `broken` needs enough runs behind it to mean anything.
- Headroom separates absorbed noise from a snapshot touching the threshold.
- Activity is bounded to the window, the default branch, and the row's run type.
- Both halves of an absorbed run count: the mint and the later matches.
- A snapshot failing the gate is listed even when it records no variant.
- Variants stay scoped to the current baseline hash.
- Only auto-minted, unexpired tolerations count toward `variant_count`.
- `needs_decision` fires on the three ways an open quarantine stops fitting.
- The activity strip is dense, split, and positions the baseline divider.
- The soft read is bounded to identifiers that can produce a row.
"""

from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest

from django.db import connections
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade import api as vr_api
from products.visual_review.backend.facade.contracts import (
    FLAKINESS_EXPIRY_SOON_DAYS,
    FLAKINESS_MIN_WINDOW_RUNS,
    FLAKINESS_RATE_DAYS,
    FLAKINESS_WINDOW_DAYS,
    PIXEL_DIFF_THRESHOLD_PERCENT,
)
from products.visual_review.backend.facade.enums import (
    ClassificationReason,
    FlakinessState,
    ReviewState,
    RunStatus,
    RunType,
    SnapshotResult,
    ToleratedReason,
)
from products.visual_review.backend.models import QuarantinedIdentifier, Repo, Run, RunSnapshot, ToleratedHash
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES, VisualReviewTeamScopedTestMixin

CURRENT_BASELINE = "baseline-current"

# What a run recorded for a snapshot, in the terms the page scores on. `soft`
# splits into the run that minted a variant and the runs that matched it later,
# because the classifier writes a different reason for each.
EXACT = "exact"
SOFT_MINT = "soft_mint"
SOFT_MATCH = "soft_match"
HARD = "hard"
HARD_NEW = "hard_new"
HARD_REMOVED = "hard_removed"

_OUTCOMES = {
    EXACT: (SnapshotResult.UNCHANGED, ClassificationReason.EXACT),
    SOFT_MINT: (SnapshotResult.UNCHANGED, ClassificationReason.BELOW_THRESHOLD),
    SOFT_MATCH: (SnapshotResult.UNCHANGED, ClassificationReason.TOLERATED_HASH),
    HARD: (SnapshotResult.CHANGED, ""),
    HARD_NEW: (SnapshotResult.NEW, ""),
    HARD_REMOVED: (SnapshotResult.REMOVED, ""),
}


def _mk_run(
    repo: Repo,
    *,
    branch: str = "master",
    run_type: str = RunType.STORYBOOK,
    superseded_by: Run | None = None,
) -> Run:
    return Run.objects.create(
        team_id=repo.team_id,
        repo=repo,
        run_type=run_type,
        branch=branch,
        commit_sha=uuid4().hex[:12],
        status=RunStatus.COMPLETED,
        completed_at=timezone.now(),
        superseded_by=superseded_by,
    )


def _mk_snapshot(
    run: Run,
    *,
    identifier: str,
    baseline_hash: str = CURRENT_BASELINE,
    outcome: str = EXACT,
    diff_percentage: float | None = None,
    tolerated_hash_match: ToleratedHash | None = None,
    review_state: str = "",
) -> RunSnapshot:
    result, reason = _OUTCOMES[outcome]
    return RunSnapshot.objects.create(
        run=run,
        team_id=run.team_id,
        identifier=identifier,
        baseline_hash=baseline_hash,
        result=result,
        classification_reason=reason,
        diff_percentage=diff_percentage,
        tolerated_hash_match=tolerated_hash_match,
        review_state=review_state,
    )


class TestFlakinessOverview(VisualReviewTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self):
        super().setUp()
        self.repo = Repo.objects.create(
            team_id=self.team.id,
            repo_external_id=4242,
            repo_full_name="PostHog/flaky",
        )
        # The universe run: newest completed master run, so its snapshots decide
        # which baseline each identifier is scored against. It is also a run
        # inside the window, so it counts toward every rate denominator.
        self.master_run = _mk_run(self.repo)

    def _mk_default_branch_run(self, *, age: timedelta, run_type: str = RunType.STORYBOOK) -> Run:
        """A completed master run aged into the past.

        Superseded, because `unique_latest_run_per_group` allows one current run
        per group and the test's own master run holds that slot.
        """
        run = _mk_run(self.repo, run_type=run_type, superseded_by=self.master_run)
        Run.objects.filter(id=run.id).update(created_at=timezone.now() - age)
        run.refresh_from_db()
        return run

    def _render(
        self,
        identifier: str,
        *,
        outcome: str,
        count: int = 1,
        age: timedelta = timedelta(hours=1),
        diff_percentage: float | None = None,
        run_type: str = RunType.STORYBOOK,
        branch: str = "master",
        baseline_hash: str = CURRENT_BASELINE,
        tolerated_hash_match: ToleratedHash | None = None,
        review_state: str = "",
    ) -> None:
        """`count` default-branch runs that each rendered `identifier` that way.

        Every run also lands in the rate denominator, which is what makes the
        share a test asserts on predictable.
        """
        for _ in range(count):
            if branch == "master":
                run = self._mk_default_branch_run(age=age, run_type=run_type)
            else:
                run = _mk_run(self.repo, branch=branch, run_type=run_type, superseded_by=self.master_run)
                Run.objects.filter(id=run.id).update(created_at=timezone.now() - age)
            _mk_snapshot(
                run,
                identifier=identifier,
                outcome=outcome,
                diff_percentage=diff_percentage,
                baseline_hash=baseline_hash,
                tolerated_hash_match=tolerated_hash_match,
                review_state=review_state,
            )

    def _mk_variant(
        self,
        *,
        identifier: str,
        alternate_hash: str,
        baseline_hash: str = CURRENT_BASELINE,
        reason: str = ToleratedReason.AUTO_THRESHOLD,
        expires_at=None,
        diff_percentage: float | None = None,
    ) -> ToleratedHash:
        return ToleratedHash.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier=identifier,
            baseline_hash=baseline_hash,
            alternate_hash=alternate_hash,
            reason=reason,
            expires_at=expires_at,
            diff_percentage=diff_percentage,
        )

    def _mk_quarantine(self, identifier: str, *, expires_at=None) -> QuarantinedIdentifier:
        return QuarantinedIdentifier.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier=identifier,
            run_type=RunType.STORYBOOK,
            reason="Known flaky",
            expires_at=expires_at,
        )

    def _entry(self, identifier: str):
        result = vr_api.get_flakiness_overview(self.repo.id)
        return next((e for e in result.entries if e.identifier == identifier), None)

    def test_a_quarantine_over_a_snapshot_still_failing_does_not_ask_to_be_lifted(self):
        # The bug this scoring replaced. A quarantine is opened for a snapshot
        # that fails the gate, and a snapshot only fails the gate when its diff
        # is over a threshold, which is the one case that records no variant.
        # Scoring on variants therefore reported every such quarantine as
        # covering a snapshot that had gone clean, and lifting it on that advice
        # turned the gate red again on the very next run.
        _mk_snapshot(self.master_run, identifier="muted", outcome=HARD)
        self._render("muted", outcome=HARD, count=20)
        self._mk_quarantine("muted")

        entry = self._entry("muted")

        assert entry is not None
        assert entry.variant_count == 0
        assert entry.hard_count == 21
        assert entry.flakiness_state == FlakinessState.BROKEN
        assert entry.needs_decision is False

    @parameterized.expand(
        [
            ("a_diff_over_the_threshold", HARD, CURRENT_BASELINE),
            # A dropped baseline leaves no hash to compare against, which is
            # what the real quarantined snapshots in this repo look like.
            ("a_baseline_that_was_never_committed", HARD_NEW, ""),
            ("a_story_that_stopped_rendering", HARD_REMOVED, CURRENT_BASELINE),
        ]
    )
    def test_every_way_of_failing_the_gate_keeps_a_quarantine_in_place(
        self, _name: str, outcome: str, baseline_hash: str
    ):
        # `gating._is_unresolved` fails the gate on every result that is not
        # UNCHANGED, so counting only CHANGED left the same bug in the two
        # quieter cases. A story whose baseline was dropped from the file comes
        # back NEW on every run, which is what a real quarantined snapshot in
        # this repo does, and it blocks a merge exactly like a CHANGED one.
        _mk_snapshot(self.master_run, identifier="muted", outcome=outcome, baseline_hash=baseline_hash)
        self._render("muted", outcome=outcome, count=20, baseline_hash=baseline_hash)
        self._mk_quarantine("muted")

        entry = self._entry("muted")

        assert entry is not None
        assert entry.hard_count == 21
        assert entry.flakiness_state == FlakinessState.BROKEN
        assert entry.needs_decision is False

    def test_a_quarantine_over_a_snapshot_that_stopped_failing_asks_to_be_lifted(self):
        _mk_snapshot(self.master_run, identifier="muted")
        self._render("muted", outcome=EXACT, count=20)
        self._mk_quarantine("muted")

        entry = self._entry("muted")

        assert entry is not None
        assert entry.hard_count == 0
        assert entry.needs_decision is True

    @parameterized.expand(
        [
            ("never_failed", 0, 20, FlakinessState.CLEAN),
            ("failed_sometimes", 2, 18, FlakinessState.UNSTABLE),
            ("failed_nearly_always", 20, 0, FlakinessState.BROKEN),
        ]
    )
    def test_state_turns_on_the_share_of_runs_that_failed(
        self, _name: str, hard_runs: int, exact_runs: int, expected: str
    ):
        # A bare count cannot separate one bad afternoon from a snapshot that
        # fails every run, and both want a different fix: the first a
        # quarantine, the second a corrected baseline.
        _mk_snapshot(self.master_run, identifier="story")
        self._render("story", outcome=HARD, count=hard_runs)
        self._render("story", outcome=EXACT, count=exact_runs)

        entry = self._entry("story")

        if expected == FlakinessState.CLEAN:
            assert entry is None  # nothing to report, so not listed at all
            return
        assert entry is not None
        assert entry.window_runs == hard_runs + exact_runs + 1  # + the universe run
        assert entry.hard_count == hard_runs
        assert entry.flakiness_state == expected

    @parameterized.expand(
        [
            ("too_few_runs_to_judge", FLAKINESS_MIN_WINDOW_RUNS - 2, FlakinessState.UNSTABLE),
            ("enough_runs_to_judge", FLAKINESS_MIN_WINDOW_RUNS - 1, FlakinessState.BROKEN),
        ]
    )
    def test_broken_needs_enough_runs_behind_it(self, _name: str, extra_hard_runs: int, expected: str):
        # One failure out of two runs is a 50% rate that means nothing, and
        # calling it broken would send somebody to fix a baseline on the
        # strength of a single bad render.
        _mk_snapshot(self.master_run, identifier="story", outcome=HARD)
        self._render("story", outcome=HARD, count=extra_hard_runs)

        entry = self._entry("story")

        assert entry is not None
        assert entry.hard_rate == 1.0
        assert entry.flakiness_state == expected

    @parameterized.expand(
        [
            ("approved", ReviewState.APPROVED),
            ("tolerated", ReviewState.TOLERATED),
        ]
    )
    def test_a_signed_off_default_branch_failure_is_not_a_flake(self, _name: str, review_state: str):
        # PostHog's own default-branch runs are observe and carry no approvals, but
        # `purpose` defaults to review, so a repo whose CI omits the flag can land an
        # approved snapshot on master. Counting it would hold a quarantine open over
        # a change somebody already accepted.
        self._render("story", outcome=HARD, count=3, review_state=review_state)
        self._render("story", outcome=HARD, count=3)

        entry = self._entry("story")

        assert entry is not None
        # Six runs rendered a hard result; only the three nobody signed off count.
        assert entry.hard_count == 3
        assert entry.flakiness_state == FlakinessState.UNSTABLE

    @parameterized.expand(
        [
            ("far_under_the_threshold", 0.01, FlakinessState.NOISY),
            ("touching_the_threshold", PIXEL_DIFF_THRESHOLD_PERCENT - 0.05, FlakinessState.AT_RISK),
        ]
    )
    def test_headroom_separates_absorbed_noise_from_a_snapshot_on_the_edge(
        self, _name: str, worst_diff: float, expected: str
    ):
        # Always being absorbed is not a safety property. A snapshot is absorbed
        # only while it stays under the threshold, so one sitting just under the
        # line is a hard failure waiting for the next unrelated restyle, and it
        # must not read the same as one with 250x of margin.
        _mk_snapshot(self.master_run, identifier="jittery")
        variant = self._mk_variant(identifier="jittery", alternate_hash="a")
        self._render("jittery", outcome=SOFT_MATCH, count=5, diff_percentage=0.01, tolerated_hash_match=variant)
        self._render("jittery", outcome=SOFT_MATCH, diff_percentage=worst_diff, tolerated_hash_match=variant)

        entry = self._entry("jittery")

        assert entry is not None
        assert entry.worst_soft_diff_percentage == worst_diff
        assert entry.flakiness_state == expected

    def test_a_snapshot_failing_the_gate_is_listed_without_recording_a_variant(self):
        # A hard failure mints nothing, so a population drawn from tolerations
        # alone cannot see the snapshots that actually block merges.
        _mk_snapshot(self.master_run, identifier="blocking")
        self._render("blocking", outcome=HARD, count=2)

        entry = self._entry("blocking")

        assert entry is not None
        assert entry.variant_count == 0
        assert entry.hard_count == 2

    @parameterized.expand(
        [
            ("the_run_that_minted_the_variant", SOFT_MINT),
            ("a_later_run_that_matched_it", SOFT_MATCH),
        ]
    )
    def test_both_halves_of_an_absorbed_run_count(self, _name: str, outcome: str):
        # The mint is classified BELOW_THRESHOLD and never linked back to the
        # row it created; later matches are classified TOLERATED_HASH. Reading
        # only one reason loses either every first occurrence or every snapshot
        # that cycles through variants it already recorded.
        _mk_snapshot(self.master_run, identifier="jittery")
        variant = self._mk_variant(identifier="jittery", alternate_hash="a")
        self._render(
            "jittery",
            outcome=outcome,
            count=3,
            diff_percentage=0.02,
            tolerated_hash_match=variant if outcome == SOFT_MATCH else None,
        )

        entry = self._entry("jittery")

        assert entry is not None
        assert entry.soft_count == 3
        assert entry.last_flaked_at is not None

    def test_a_deliberate_toleration_is_not_counted_as_rendering_noise(self):
        # A human or agent toleration can accept a diff well over the pixel
        # threshold, and the classifier copies that percentage onto every later
        # match. Counting those as absorbed noise drove headroom to zero and
        # labelled a snapshot somebody had already signed off on as at risk.
        _mk_snapshot(self.master_run, identifier="accepted")
        human = self._mk_variant(identifier="accepted", alternate_hash="a", reason=ToleratedReason.HUMAN)
        auto = self._mk_variant(identifier="accepted", alternate_hash="b", diff_percentage=0.01)
        for tolerated in (human, human, auto):
            run = self._mk_default_branch_run(age=timedelta(hours=1))
            _mk_snapshot(
                run,
                identifier="accepted",
                outcome=SOFT_MATCH,
                diff_percentage=12.0 if tolerated is human else 0.01,
                tolerated_hash_match=tolerated,
            )

        entry = self._entry("accepted")

        assert entry is not None
        assert entry.soft_count == 1  # only the auto-minted match
        assert entry.worst_soft_diff_percentage == 0.01
        assert entry.flakiness_state == FlakinessState.NOISY

    def test_the_rate_denominator_covers_the_same_days_as_its_numerator(self):
        # The numerator is summed from per-day buckets while the denominator was
        # counted from a timestamp, so the oldest partial day put runs in the
        # denominator whose failures never reached the numerator. Every rate
        # came out low, and how low depended on the time of day.
        _mk_snapshot(self.master_run, identifier="story", outcome=HARD)
        self._render("story", outcome=HARD, count=6, age=timedelta(days=FLAKINESS_RATE_DAYS - 1, hours=12))

        entry = self._entry("story")

        assert entry is not None
        assert entry.hard_count == entry.window_runs
        assert entry.hard_rate == 1.0

    @parameterized.expand(
        [
            ("inside_the_rate_span", timedelta(days=FLAKINESS_RATE_DAYS - 2), 3, 3),
            ("older_than_the_rate_span", timedelta(days=FLAKINESS_RATE_DAYS + 2), 0, 3),
            ("older_than_the_window", timedelta(days=FLAKINESS_WINDOW_DAYS + 5), 0, 0),
        ]
    )
    def test_rates_read_the_rate_span_and_the_strip_reads_the_window(
        self, _name: str, age: timedelta, expected_hard: int, expected_strip: int
    ):
        # The rate has to lapse before the strip does. A quarantine over a
        # snapshot that stopped failing last week must become liftable, and
        # scoring it over the whole window would keep reporting failures it no
        # longer produces. The strip still shows them, so the history is not
        # lost, just no longer counted against it.
        _mk_snapshot(self.master_run, identifier="story")
        self._render("story", outcome=HARD, count=3, age=age)
        self._mk_quarantine("story")  # keeps the row listed once activity ages out

        entry = self._entry("story")

        assert entry is not None
        assert entry.hard_count == expected_hard
        assert sum(entry.daily_hard_counts) == expected_strip
        assert entry.needs_decision is (expected_hard == 0)

    def test_activity_on_a_pr_branch_does_not_count(self):
        # A PR rendering a difference is a property of that branch, not evidence
        # the default branch is unstable.
        _mk_snapshot(self.master_run, identifier="pr-only")
        self._render("pr-only", outcome=HARD, count=3, branch="feat/something")
        self._mk_quarantine("pr-only")

        entry = self._entry("pr-only")

        assert entry is not None
        assert entry.hard_count == 0

    def test_activity_does_not_leak_between_run_types(self):
        # A row is one `(run_type, identifier)`. A storybook failure says
        # nothing about the playwright row for the same identifier.
        playwright_run = _mk_run(self.repo, run_type=RunType.PLAYWRIGHT)
        _mk_snapshot(playwright_run, identifier="shared")
        _mk_snapshot(self.master_run, identifier="shared")
        self._render("shared", outcome=HARD, count=3)

        result = vr_api.get_flakiness_overview(self.repo.id)
        by_type = {e.run_type: e for e in result.entries if e.identifier == "shared"}

        assert by_type[RunType.STORYBOOK].hard_count == 3
        assert RunType.PLAYWRIGHT not in by_type

    def test_a_rate_cannot_exceed_one(self):
        # The denominator counts runs of the run type, not runs that rendered
        # this identifier, so a row could otherwise report more failures than
        # there were runs.
        _mk_snapshot(self.master_run, identifier="shared")
        _mk_run(self.repo, run_type=RunType.PLAYWRIGHT)
        self._render("shared", outcome=HARD, count=4, run_type=RunType.PLAYWRIGHT)

        entry = next(
            e
            for e in vr_api.get_flakiness_overview(self.repo.id).entries
            if e.identifier == "shared" and e.run_type == RunType.PLAYWRIGHT
        )

        assert entry.hard_count == 4
        assert entry.hard_rate <= 1.0

    def test_variants_against_a_superseded_baseline_are_not_counted(self):
        _mk_snapshot(self.master_run, identifier="redesigned")
        for index in range(5):
            self._mk_variant(identifier="redesigned", alternate_hash=f"old-{index}", baseline_hash="baseline-previous")
        self._mk_variant(identifier="redesigned", alternate_hash="new-0")

        entry = self._entry("redesigned")

        assert entry is not None
        assert entry.variant_count == 1

    def test_a_snapshot_whose_only_variants_predate_the_baseline_move_is_not_listed(self):
        _mk_snapshot(self.master_run, identifier="redesigned")
        for index in range(5):
            self._mk_variant(identifier="redesigned", alternate_hash=f"old-{index}", baseline_hash="baseline-previous")

        assert self._entry("redesigned") is None

    @parameterized.expand(
        [
            ("human_tolerations", ToleratedReason.HUMAN),
            ("agent_tolerations", ToleratedReason.AGENT),
        ]
    )
    def test_deliberate_tolerations_are_not_counted_as_variants(self, _name: str, reason: str):
        _mk_snapshot(self.master_run, identifier="accepted")
        self._mk_variant(identifier="accepted", alternate_hash="a", reason=reason)

        assert self._entry("accepted") is None

    def test_expired_variants_are_not_counted(self):
        _mk_snapshot(self.master_run, identifier="lapsed")
        self._mk_variant(identifier="lapsed", alternate_hash="live")
        self._mk_variant(
            identifier="lapsed",
            alternate_hash="dead",
            expires_at=timezone.now() - timedelta(days=1),
        )

        entry = self._entry("lapsed")

        assert entry is not None
        assert entry.variant_count == 1

    def test_the_soft_read_skips_identifiers_that_cannot_produce_a_row(self):
        # Absorbed rows are the common case rather than the rare one, so an
        # unbounded read would scan most of the window's snapshots to throw the
        # result away. Only the hard read can afford to run wide.
        _mk_snapshot(self.master_run, identifier="quiet")
        _mk_snapshot(self.master_run, identifier="flaky")
        self._mk_variant(identifier="flaky", alternate_hash="a")

        with CaptureQueriesContext(connections[WRITER_DB]) as captured:
            vr_api.get_flakiness_overview(self.repo.id)

        soft_queries = [q["sql"] for q in captured.captured_queries if ClassificationReason.TOLERATED_HASH in q["sql"]]
        assert soft_queries
        for sql in soft_queries:
            assert "flaky" in sql
            assert "quiet" not in sql

    def test_a_quarantine_on_a_snapshot_without_a_baseline_is_still_listed(self):
        # Quarantining does not require a baseline, and the empty state promises
        # that quarantining alone puts a snapshot on this page.
        _mk_snapshot(self.master_run, identifier="brand-new", baseline_hash="")
        self._mk_quarantine("brand-new")

        result = vr_api.get_flakiness_overview(self.repo.id)

        assert [e.identifier for e in result.entries] == ["brand-new"]
        assert result.totals.quarantined == 1

    def test_a_quarantine_survives_a_repo_with_no_completed_default_run(self):
        # Quarantining does not wait for a first master run, and somebody is
        # relying on the snapshot being skipped meanwhile.
        Run.objects.filter(repo=self.repo).update(status=RunStatus.PENDING)
        self._mk_quarantine("muted-early")

        result = vr_api.get_flakiness_overview(self.repo.id)

        assert [e.identifier for e in result.entries] == ["muted-early"]
        assert result.totals.tracked == 0
        assert result.totals.quarantined == 1

    def test_the_baseline_for_a_run_type_does_not_depend_on_branch_order(self):
        # One run per branch and run type means a repo on both master and main
        # has two, and the row identity carries no branch. Without picking the
        # newest, two identical requests could report different baselines.
        main_run = _mk_run(self.repo, branch="main")
        Run.objects.filter(id=main_run.id).update(created_at=timezone.now() - timedelta(days=3))
        _mk_snapshot(main_run, identifier="shared", baseline_hash="baseline-stale")
        _mk_snapshot(self.master_run, identifier="shared")
        self._mk_variant(identifier="shared", alternate_hash="a")

        entry = self._entry("shared")

        assert entry is not None
        assert entry.variant_count == 1

    @parameterized.expand(
        [
            ("expiring_soon", timedelta(days=FLAKINESS_EXPIRY_SOON_DAYS - 1), True),
            ("expiring_later", timedelta(days=FLAKINESS_EXPIRY_SOON_DAYS + 5), False),
            ("open_ended_but_still_failing", None, False),
        ]
    )
    def test_needs_decision_flags_a_quarantine_that_stopped_fitting(
        self, _name: str, expires_in: timedelta | None, expected: bool
    ):
        _mk_snapshot(self.master_run, identifier="muted")
        self._render("muted", outcome=HARD, count=3)
        self._mk_quarantine(
            "muted",
            expires_at=timezone.now() + expires_in if expires_in is not None else None,
        )

        entry = self._entry("muted")

        assert entry is not None
        assert entry.needs_decision is expected

    def test_rows_needing_a_decision_survive_the_entry_cap(self):
        # The cap slices the sorted list, so ordering decides what a client can
        # still act on. A quarantine over a snapshot that stopped failing is the
        # one row somebody has to answer, and it carries the least activity.
        _mk_snapshot(self.master_run, identifier="muted")
        self._mk_quarantine("muted")
        _mk_snapshot(self.master_run, identifier="noisy")
        variant = self._mk_variant(identifier="noisy", alternate_hash="a")
        self._render("noisy", outcome=SOFT_MATCH, count=5, diff_percentage=0.01, tolerated_hash_match=variant)

        result = vr_api.get_flakiness_overview(self.repo.id)

        assert [e.identifier for e in result.entries] == ["muted", "noisy"]

    def test_snapshots_with_nothing_to_report_are_not_listed(self):
        _mk_snapshot(self.master_run, identifier="stable")
        _mk_snapshot(self.master_run, identifier="flaky")
        self._mk_variant(identifier="flaky", alternate_hash="a")

        result = vr_api.get_flakiness_overview(self.repo.id)

        assert [e.identifier for e in result.entries] == ["flaky"]
        assert result.totals.listed == 1
        assert result.totals.tracked == 2

    def test_the_denominator_counts_only_snapshots_with_a_baseline(self):
        _mk_snapshot(self.master_run, identifier="compared")
        _mk_snapshot(self.master_run, identifier="brand-new", baseline_hash="")

        result = vr_api.get_flakiness_overview(self.repo.id)

        assert result.totals.tracked == 1

    def test_the_activity_strip_is_dense_split_and_places_today_last(self):
        _mk_snapshot(self.master_run, identifier="flaky")
        variant = self._mk_variant(identifier="flaky", alternate_hash="a")
        self._render("flaky", outcome=HARD, age=timedelta(0))
        self._render("flaky", outcome=SOFT_MATCH, age=timedelta(0), diff_percentage=0.01, tolerated_hash_match=variant)
        self._render("flaky", outcome=HARD, age=timedelta(days=FLAKINESS_WINDOW_DAYS + 10))

        entry = self._entry("flaky")

        assert entry is not None
        assert len(entry.daily_hard_counts) == FLAKINESS_WINDOW_DAYS
        assert len(entry.daily_soft_counts) == FLAKINESS_WINDOW_DAYS
        assert entry.daily_hard_counts[-1] == 1
        assert entry.daily_soft_counts[-1] == 1
        assert sum(entry.daily_hard_counts) == 1  # the aged run is outside the window

    def test_the_baseline_divider_is_absent_when_the_baseline_moved_before_the_window(self):
        older_run = _mk_run(self.repo, superseded_by=self.master_run)
        _mk_snapshot(older_run, identifier="flaky", outcome=HARD)
        Run.objects.filter(id=older_run.id).update(
            created_at=timezone.now() - timedelta(days=FLAKINESS_WINDOW_DAYS + 10)
        )
        _mk_snapshot(self.master_run, identifier="flaky")
        self._mk_variant(identifier="flaky", alternate_hash="a")

        entry = self._entry("flaky")

        assert entry is not None
        assert entry.baseline_moved_day_index is None
        assert entry.baseline_age_days is not None
        assert entry.baseline_age_days >= FLAKINESS_WINDOW_DAYS

    def test_totals_count_the_whole_population(self):
        # The denominator is every storybook run in the window, so the runs
        # that rendered `jittery` dilute `wrecked`'s rate too. Enough hard runs
        # to clear the broken band anyway.
        _mk_snapshot(self.master_run, identifier="wrecked", outcome=HARD)
        self._render("wrecked", outcome=HARD, count=20)
        _mk_snapshot(self.master_run, identifier="jittery")
        variant = self._mk_variant(identifier="jittery", alternate_hash="a")
        self._render("jittery", outcome=SOFT_MATCH, diff_percentage=0.01, tolerated_hash_match=variant)
        _mk_snapshot(self.master_run, identifier="stable")
        self._mk_quarantine("wrecked")

        totals = vr_api.get_flakiness_overview(self.repo.id).totals

        assert totals.tracked == 3
        assert totals.listed == 2
        assert totals.broken == 1
        assert totals.noisy == 1
        assert totals.quarantined == 1
        assert totals.by_run_type == {RunType.STORYBOOK: 2}

    def test_endpoint_serializes_the_overview(self):
        _mk_snapshot(self.master_run, identifier="flaky")
        variant = self._mk_variant(identifier="flaky", alternate_hash="a", diff_percentage=0.04)
        self._render("flaky", outcome=SOFT_MATCH, diff_percentage=0.04, tolerated_hash_match=variant)

        url = f"/api/projects/{self.team.id}/visual_review/repos/{self.repo.id}/flakiness/"
        response = self.client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert [entry["identifier"] for entry in data["entries"]] == ["flaky"]
        entry = data["entries"][0]
        assert entry["variant_count"] == 1
        assert entry["soft_count"] == 1
        assert entry["flakiness_state"] == FlakinessState.NOISY
        assert len(entry["daily_hard_counts"]) == FLAKINESS_WINDOW_DAYS
        assert data["totals"]["tracked"] == 1

    def test_endpoint_404_for_unknown_repo(self):
        url = f"/api/projects/{self.team.id}/visual_review/repos/{uuid4()}/flakiness/"
        response = self.client.get(url)

        assert response.status_code == 404
