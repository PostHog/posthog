"""Tests for the flakiness overview.

Coverage:
- Variants are scoped to the current baseline hash, so a baseline move resets the score.
- Only auto-minted, unexpired tolerations count, matching what the classifier can match.
- `unstable` against `settled` turns on recency, not on the count.
- Only identifiers carrying variants or a quarantine are listed.
- `needs_decision` fires on the three ways an open quarantine stops fitting.
- The activity strip is dense and positions the baseline divider.
"""

from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized

from products.visual_review.backend.facade import api as vr_api
from products.visual_review.backend.facade.contracts import (
    FLAKINESS_EXPIRY_SOON_DAYS,
    FLAKINESS_RECENT_DAYS,
    FLAKINESS_STRIP_DAYS,
)
from products.visual_review.backend.facade.enums import (
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
) -> RunSnapshot:
    return RunSnapshot.objects.create(
        run=run,
        team_id=run.team_id,
        identifier=identifier,
        baseline_hash=baseline_hash,
        result=result,
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
    ) -> ToleratedHash:
        row = ToleratedHash.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier=identifier,
            baseline_hash=baseline_hash,
            alternate_hash=alternate_hash,
            reason=reason,
            expires_at=expires_at,
            diff_percentage=diff_percentage,
        )
        ToleratedHash.objects.filter(id=row.id).update(created_at=timezone.now() - age)
        row.refresh_from_db()
        return row

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

    def test_snapshots_with_nothing_to_report_are_not_listed(self):
        _mk_snapshot(self.master_run, identifier="stable")
        _mk_snapshot(self.master_run, identifier="flaky")
        self._mk_variant(identifier="flaky", alternate_hash="a")

        result = vr_api.get_flakiness_overview(self.repo.id)

        assert [e.identifier for e in result.entries] == ["flaky"]
        assert result.totals.listed == 1
        assert result.totals.tracked == 2

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
