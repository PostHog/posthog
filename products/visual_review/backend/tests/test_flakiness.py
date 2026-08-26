"""Tests for the flakiness overview.

Coverage:
- Variants are scoped to the current baseline hash, so a baseline move resets the score.
- Only auto-minted, unexpired tolerations count, matching what the classifier can match.
- `unstable` against `settled` turns on recency, not on the count.
- Only identifiers carrying variants or a quarantine are listed.
- `needs_decision` fires on the three ways an open quarantine stops fitting.
- The activity strip is dense and positions the baseline divider.
- Recency comes from runs that matched a variant, not from when it was minted.
- The history scan is bounded to identifiers that can produce a row.
- A variant's first occurrence counts, not just later matches of it.
- A quarantine without a current baseline is still listed.
- Recency is scoped to the default branch and to the row's own run type.
- Recency reports the run's time, not when the toleration row was written.
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
    FLAKINESS_RECENT_DAYS,
    FLAKINESS_STRIP_DAYS,
)
from products.visual_review.backend.facade.enums import (
    ClassificationReason,
    FlakinessState,
    RunStatus,
    RunType,
    SnapshotResult,
    ToleratedReason,
)
from products.visual_review.backend.models import QuarantinedIdentifier, Repo, Run, RunSnapshot, ToleratedHash
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES, VisualReviewTeamScopedTestMixin

CURRENT_BASELINE = "baseline-current"


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
    result: str = SnapshotResult.UNCHANGED,
    tolerated_hash_match: ToleratedHash | None = None,
) -> RunSnapshot:
    return RunSnapshot.objects.create(
        run=run,
        team_id=run.team_id,
        identifier=identifier,
        baseline_hash=baseline_hash,
        result=result,
        tolerated_hash_match=tolerated_hash_match,
        classification_reason=ClassificationReason.TOLERATED_HASH if tolerated_hash_match else "",
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
        self.master_run = _mk_run(self.repo)

    def _mk_variant(
        self,
        *,
        identifier: str,
        alternate_hash: str,
        baseline_hash: str = CURRENT_BASELINE,
        reason: str = ToleratedReason.AUTO_THRESHOLD,
        age: timedelta = timedelta(days=1),
        expires_at=None,
        diff_percentage: float | None = None,
        source_run: Run | None = None,
    ) -> ToleratedHash:
        # `diffing.py` always records the run that minted a variant, and the
        # aggregate reads recency through it, so a fixture without one does not
        # model anything real.
        minting_run = source_run
        if minting_run is None:
            minting_run = self._mk_default_branch_run(age=age)
            # The minting run rendered this snapshot, which is why it produced a
            # variant. Without the row the run can win the universe query while
            # carrying no snapshots, which no real run does.
            _mk_snapshot(minting_run, identifier=identifier, baseline_hash=baseline_hash)
        row = ToleratedHash.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier=identifier,
            baseline_hash=baseline_hash,
            alternate_hash=alternate_hash,
            reason=reason,
            expires_at=expires_at,
            diff_percentage=diff_percentage,
            source_run=minting_run,
        )
        ToleratedHash.objects.filter(id=row.id).update(created_at=timezone.now() - age)
        row.refresh_from_db()
        return row

    def _mk_default_branch_run(self, *, age: timedelta) -> Run:
        """A completed master run aged into the past.

        Superseded, because `unique_latest_run_per_group` allows one current run
        per group and the test's own master run holds that slot.
        """
        run = _mk_run(self.repo, superseded_by=self.master_run)
        Run.objects.filter(id=run.id).update(created_at=timezone.now() - age)
        run.refresh_from_db()
        return run

    def _mk_match(self, tolerated: ToleratedHash, *, age: timedelta) -> Run:
        """A run that rendered `tolerated` again and matched it.

        Repeat matches are the only evidence a snapshot still flakes once every
        variant it produces is already recorded.
        """
        run = self._mk_default_branch_run(age=age)
        _mk_snapshot(
            run,
            identifier=tolerated.identifier,
            baseline_hash=tolerated.baseline_hash,
            tolerated_hash_match=tolerated,
        )
        return run

    def _entry(self, identifier: str):
        result = vr_api.get_flakiness_overview(self.repo.id)
        return next((e for e in result.entries if e.identifier == identifier), None)

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
    def test_deliberate_tolerations_are_not_counted_as_flakiness(self, _name: str, reason: str):
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

    @parameterized.expand(
        [
            ("just_inside_the_window", timedelta(days=FLAKINESS_RECENT_DAYS - 1), FlakinessState.UNSTABLE),
            ("just_outside_the_window", timedelta(days=FLAKINESS_RECENT_DAYS + 1), FlakinessState.SETTLED),
        ]
    )
    def test_state_turns_on_recency_not_on_count(self, _name: str, age: timedelta, expected: str):
        _mk_snapshot(self.master_run, identifier="noisy")
        for index in range(20):
            self._mk_variant(identifier="noisy", alternate_hash=f"a-{index}", age=age)

        entry = self._entry("noisy")

        assert entry is not None
        assert entry.variant_count == 20
        assert entry.flakiness_state == expected

    def test_a_snapshot_cycling_through_known_variants_stays_unstable(self):
        # The mint site uses get_or_create, so a repeat match never refreshes
        # ToleratedHash.created_at. Scoring recency off that timestamp would
        # call this snapshot settled while it still fails to render the same
        # way twice, which is the worst case this page exists to find.
        _mk_snapshot(self.master_run, identifier="cycling")
        old = timedelta(days=FLAKINESS_RECENT_DAYS + 20)
        for index in range(3):
            variant = self._mk_variant(identifier="cycling", alternate_hash=f"a-{index}", age=old)
            self._mk_match(variant, age=timedelta(hours=6))
        assert all(t.created_at < timezone.now() - old + timedelta(hours=1) for t in ToleratedHash.objects.all())

        entry = self._entry("cycling")

        assert entry is not None
        assert entry.variant_count == 3
        assert entry.flakiness_state == FlakinessState.UNSTABLE

    def test_the_history_scan_skips_identifiers_that_cannot_produce_a_row(self):
        # The era query reaches over the repo's whole default-branch history,
        # so the identifier list is the only thing bounding it. Widening it back
        # to the universe would scan every quiet snapshot to throw the result
        # away, which is most of them on a healthy repo.
        _mk_snapshot(self.master_run, identifier="quiet")
        _mk_snapshot(self.master_run, identifier="flaky")
        self._mk_variant(identifier="flaky", alternate_hash="a")

        with CaptureQueriesContext(connections[WRITER_DB]) as captured:
            vr_api.get_flakiness_overview(self.repo.id)

        # The history queries are the ones that join RunSnapshot to Run and
        # aggregate over run timestamps.
        history_queries = [
            q["sql"]
            for q in captured.captured_queries
            if "visual_review_run" in q["sql"]
            and "MAX(" in q["sql"].upper()
            and "visual_review_runsnapshot" in q["sql"]
        ]
        assert history_queries
        for sql in history_queries:
            assert "flaky" in sql
            assert "quiet" not in sql

    def test_a_first_time_variant_counts_as_a_flake(self):
        # The run that mints a variant is classified BELOW_THRESHOLD and never
        # linked to the row it created, so run matches alone miss every first
        # occurrence. That would report a snapshot that started flaking today
        # as settled, which is the opposite of what the tile promises.
        _mk_snapshot(self.master_run, identifier="just-started")
        row = self._mk_variant(identifier="just-started", alternate_hash="first")
        assert not RunSnapshot.objects.filter(tolerated_hash_match=row).exists()

        entry = self._entry("just-started")

        assert entry is not None
        assert entry.variant_count == 1
        assert entry.flakiness_state == FlakinessState.UNSTABLE

    def test_a_quarantine_on_a_snapshot_without_a_baseline_is_still_listed(self):
        # Quarantining does not require a baseline, and the empty state promises
        # that quarantining alone puts a snapshot on this page.
        _mk_snapshot(self.master_run, identifier="brand-new", baseline_hash="")
        QuarantinedIdentifier.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier="brand-new",
            run_type=RunType.STORYBOOK,
            reason="Flaky from the first run",
        )

        result = vr_api.get_flakiness_overview(self.repo.id)

        assert [e.identifier for e in result.entries] == ["brand-new"]
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

    def test_a_variant_minted_on_a_pr_branch_does_not_count_as_recent(self):
        # diffing.py mints from PR runs too. A PR rendering a variant is a
        # property of that branch, not evidence the default branch is unstable.
        _mk_snapshot(self.master_run, identifier="pr-only")
        pr_run = _mk_run(self.repo, branch="feat/something", superseded_by=self.master_run)
        self._mk_variant(identifier="pr-only", alternate_hash="from-pr", source_run=pr_run)

        entry = self._entry("pr-only")

        assert entry is not None
        assert entry.variant_count == 1
        assert entry.last_flaked_at is None
        assert entry.flakiness_state == FlakinessState.SETTLED

    def test_recency_does_not_leak_between_run_types(self):
        # Matching ignores run type, but a row does not. A recent storybook
        # flake says nothing about the playwright row for the same identifier.
        playwright_run = _mk_run(self.repo, run_type=RunType.PLAYWRIGHT)
        _mk_snapshot(playwright_run, identifier="shared")
        _mk_snapshot(self.master_run, identifier="shared")
        self._mk_variant(identifier="shared", alternate_hash="a", age=timedelta(hours=2))

        result = vr_api.get_flakiness_overview(self.repo.id)
        by_type = {e.run_type: e for e in result.entries if e.identifier == "shared"}

        # Both rows exist and both count the variant, because the classifier
        # would match it either way. Only the run type that actually rendered it
        # recently is unstable.
        assert by_type[RunType.STORYBOOK].flakiness_state == FlakinessState.UNSTABLE
        assert by_type[RunType.PLAYWRIGHT].variant_count == 1
        assert by_type[RunType.PLAYWRIGHT].last_flaked_at is None
        assert by_type[RunType.PLAYWRIGHT].flakiness_state == FlakinessState.SETTLED

    def test_a_quarantine_survives_a_repo_with_no_completed_default_run(self):
        # Quarantining does not wait for a first master run, and somebody is
        # relying on the snapshot being skipped meanwhile.
        Run.objects.filter(repo=self.repo).update(status=RunStatus.PENDING)
        QuarantinedIdentifier.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier="muted-early",
            run_type=RunType.STORYBOOK,
            reason="Flaky since the first run",
        )

        result = vr_api.get_flakiness_overview(self.repo.id)

        assert [e.identifier for e in result.entries] == ["muted-early"]
        assert result.totals.tracked == 0
        assert result.totals.quarantined == 1

    def test_recency_reports_when_the_run_happened_not_when_the_row_was_written(self):
        # ToleratedHash.created_at is when the row was written, which can lag or
        # be retried. Reporting that would call an old capture newly unstable.
        _mk_snapshot(self.master_run, identifier="delayed")
        stale_run = self._mk_default_branch_run(age=timedelta(days=FLAKINESS_RECENT_DAYS + 5))
        _mk_snapshot(stale_run, identifier="delayed")
        row = self._mk_variant(identifier="delayed", alternate_hash="a", source_run=stale_run)
        ToleratedHash.objects.filter(id=row.id).update(created_at=timezone.now())

        entry = self._entry("delayed")

        assert entry is not None
        assert entry.flakiness_state == FlakinessState.SETTLED

    def test_rows_needing_a_decision_survive_the_entry_cap(self):
        # The cap slices the sorted list, so ordering decides what a client can
        # still act on. A clean quarantine has no variants and would sort last
        # under a count-only order, while the tiles kept counting it.
        _mk_snapshot(self.master_run, identifier="muted")
        QuarantinedIdentifier.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier="muted",
            run_type=RunType.STORYBOOK,
            reason="Known flaky",
        )
        _mk_snapshot(self.master_run, identifier="noisy")
        for index in range(5):
            self._mk_variant(identifier="noisy", alternate_hash=f"a-{index}")

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

    def test_a_quarantined_snapshot_with_no_variants_is_listed_as_clean(self):
        _mk_snapshot(self.master_run, identifier="muted")
        QuarantinedIdentifier.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier="muted",
            run_type=RunType.STORYBOOK,
            reason="Async content loading race condition",
        )

        entry = self._entry("muted")

        assert entry is not None
        assert entry.variant_count == 0
        assert entry.flakiness_state == FlakinessState.CLEAN
        assert entry.is_quarantined is True

    @parameterized.expand(
        [
            ("expiring_soon", timedelta(days=FLAKINESS_EXPIRY_SOON_DAYS - 1), 3, True),
            ("expiring_later", timedelta(days=FLAKINESS_EXPIRY_SOON_DAYS + 5), 3, False),
            ("open_ended_but_still_flaking", None, 3, False),
        ]
    )
    def test_needs_decision_flags_a_quarantine_that_stopped_fitting(
        self, _name: str, expires_in: timedelta | None, variant_count: int, expected: bool
    ):
        _mk_snapshot(self.master_run, identifier="muted")
        for index in range(variant_count):
            self._mk_variant(identifier="muted", alternate_hash=f"a-{index}")
        QuarantinedIdentifier.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier="muted",
            run_type=RunType.STORYBOOK,
            reason="Known flaky",
            expires_at=timezone.now() + expires_in if expires_in is not None else None,
        )

        entry = self._entry("muted")

        assert entry is not None
        assert entry.needs_decision is expected

    def test_an_open_ended_quarantine_over_a_clean_snapshot_needs_a_decision(self):
        _mk_snapshot(self.master_run, identifier="muted")
        QuarantinedIdentifier.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier="muted",
            run_type=RunType.STORYBOOK,
            reason="Known flaky",
        )

        entry = self._entry("muted")

        assert entry is not None
        assert entry.needs_decision is True

    def test_the_activity_strip_is_dense_and_places_recent_variants_last(self):
        _mk_snapshot(self.master_run, identifier="flaky")
        self._mk_variant(identifier="flaky", alternate_hash="today", age=timedelta(0))
        self._mk_variant(identifier="flaky", alternate_hash="old", age=timedelta(days=FLAKINESS_STRIP_DAYS + 10))

        entry = self._entry("flaky")

        assert entry is not None
        assert len(entry.daily_variant_counts) == FLAKINESS_STRIP_DAYS
        assert entry.daily_variant_counts[-1] == 1
        assert sum(entry.daily_variant_counts) == 1

    def test_the_baseline_divider_is_absent_when_the_baseline_moved_before_the_window(self):
        older_run = _mk_run(self.repo, superseded_by=self.master_run)
        _mk_snapshot(older_run, identifier="flaky", result=SnapshotResult.CHANGED)
        Run.objects.filter(id=older_run.id).update(
            created_at=timezone.now() - timedelta(days=FLAKINESS_STRIP_DAYS + 10)
        )
        _mk_snapshot(self.master_run, identifier="flaky")
        self._mk_variant(identifier="flaky", alternate_hash="a")

        entry = self._entry("flaky")

        assert entry is not None
        assert entry.baseline_moved_day_index is None
        assert entry.baseline_age_days is not None
        assert entry.baseline_age_days >= FLAKINESS_STRIP_DAYS

    def test_totals_count_the_whole_population(self):
        _mk_snapshot(self.master_run, identifier="hot")
        _mk_snapshot(self.master_run, identifier="cold")
        _mk_snapshot(self.master_run, identifier="stable")
        self._mk_variant(identifier="hot", alternate_hash="a", age=timedelta(days=1))
        self._mk_variant(identifier="cold", alternate_hash="b", age=timedelta(days=FLAKINESS_RECENT_DAYS + 5))
        QuarantinedIdentifier.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier="hot",
            run_type=RunType.STORYBOOK,
            reason="Known flaky",
        )

        totals = vr_api.get_flakiness_overview(self.repo.id).totals

        assert totals.tracked == 3
        assert totals.listed == 2
        assert totals.unstable == 1
        assert totals.settled == 1
        assert totals.quarantined == 1
        assert totals.by_run_type == {RunType.STORYBOOK: 2}

    def test_endpoint_serializes_the_overview(self):
        _mk_snapshot(self.master_run, identifier="flaky")
        self._mk_variant(identifier="flaky", alternate_hash="a", diff_percentage=0.04)

        url = f"/api/projects/{self.team.id}/visual_review/repos/{self.repo.id}/flakiness/"
        response = self.client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert [entry["identifier"] for entry in data["entries"]] == ["flaky"]
        entry = data["entries"][0]
        assert entry["variant_count"] == 1
        assert entry["flakiness_state"] == FlakinessState.UNSTABLE
        assert len(entry["daily_variant_counts"]) == FLAKINESS_STRIP_DAYS
        assert data["totals"]["tracked"] == 1

    def test_endpoint_404_for_unknown_repo(self):
        url = f"/api/projects/{self.team.id}/visual_review/repos/{uuid4()}/flakiness/"
        response = self.client.get(url)

        assert response.status_code == 404
