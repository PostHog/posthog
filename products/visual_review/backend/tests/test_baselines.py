"""Tests for the snapshots-overview endpoint and the underlying logic.

Coverage:
- Universe is anchored on the latest non-superseded run on the default branch.
- Truncation past the configured cap, sorted by run completion time desc.
- Tolerate counts respect the 30d / 90d windows.
- Active vs expired quarantine filtering.
- Sparkline buckets (clean / tolerated / changed / quarantined).
- Totals computed across the universe (not the truncated slice).
- Browser metadata flows through for Playwright runs.
"""

from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from products.visual_review.backend.facade import api as vr_api
from products.visual_review.backend.facade.contracts import BASELINE_OVERVIEW_MAX_ENTRIES, BASELINE_SPARKLINE_DAYS
from products.visual_review.backend.facade.enums import RunStatus, RunType, SnapshotResult, ToleratedReason
from products.visual_review.backend.models import Artifact, QuarantinedIdentifier, Repo, Run, RunSnapshot, ToleratedHash
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


def _mk_artifact(repo: Repo, content_hash: str, *, with_thumbnail: str | None = None) -> Artifact:
    artifact = Artifact.objects.create(
        repo=repo,
        team_id=repo.team_id,
        content_hash=content_hash,
        storage_path=f"path/{content_hash}",
        width=320,
        height=200,
    )
    if with_thumbnail:
        thumb = Artifact.objects.create(
            repo=repo,
            team_id=repo.team_id,
            content_hash=with_thumbnail,
            storage_path=f"thumb/{with_thumbnail}",
            width=64,
            height=40,
        )
        artifact.thumbnail = thumb
        artifact.save(update_fields=["thumbnail"])
    return artifact


def _mk_run(
    repo: Repo,
    *,
    branch: str = "master",
    run_type: str = RunType.STORYBOOK,
    completed_offset: timedelta = timedelta(hours=0),
    superseded_by: Run | None = None,
) -> Run:
    completed = timezone.now() - completed_offset
    return Run.objects.create(
        team_id=repo.team_id,
        repo=repo,
        run_type=run_type,
        branch=branch,
        commit_sha=uuid4().hex[:12],
        status=RunStatus.COMPLETED,
        completed_at=completed,
        superseded_by=superseded_by,
    )


def _mk_snapshot(
    run: Run,
    *,
    identifier: str,
    result: str = SnapshotResult.UNCHANGED,
    artifact: Artifact | None = None,
    is_quarantined: bool = False,
    tolerated_match: ToleratedHash | None = None,
    metadata: dict | None = None,
    created_offset: timedelta = timedelta(hours=0),
) -> RunSnapshot:
    snap = RunSnapshot.objects.create(
        run=run,
        team_id=run.team_id,
        identifier=identifier,
        current_hash=artifact.content_hash if artifact else "",
        current_artifact=artifact,
        result=result,
        is_quarantined=is_quarantined,
        tolerated_hash_match=tolerated_match,
        metadata=metadata or {},
    )
    if created_offset:
        # Force created_at backwards for sparkline window tests.
        target = timezone.now() - created_offset
        RunSnapshot.objects.filter(id=snap.id).update(created_at=target)
        # Also push the parent run's created_at — sparkline filters on run.created_at.
        Run.objects.filter(id=run.id).update(created_at=target)
        snap.refresh_from_db()
    return snap


class TestBaselinesOverview(APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self):
        super().setUp()
        self.repo = Repo.objects.create(
            team_id=self.team.id,
            repo_external_id=12345,
            repo_full_name="org/repo",
        )

    def test_empty_repo_returns_empty_universe(self):
        result = vr_api.get_baselines_overview(self.repo.id)
        assert result.entries == []
        assert result.totals.all_snapshots == 0
        assert result.totals.recently_tolerated == 0
        assert result.totals.frequently_tolerated == 0
        assert result.totals.currently_quarantined == 0
        assert result.totals.by_run_type == {}
        assert result.truncated is False

    def test_universe_anchored_on_latest_non_superseded_master_run(self):
        # Old master run — will be superseded BEFORE inserting the new one
        # (the partial unique index `unique_latest_run_per_group` forbids two
        # non-superseded rows per (repo, branch, run_type)).
        old = _mk_run(self.repo, branch="master", completed_offset=timedelta(days=2))
        _mk_snapshot(old, identifier="old-only", result=SnapshotResult.UNCHANGED)

        # PR-branch run on the same repo — should NOT contribute (not master).
        pr_run = _mk_run(self.repo, branch="my-feature", completed_offset=timedelta(hours=1))
        _mk_snapshot(pr_run, identifier="pr-only")

        # Supersede `old` first (real flow does this before insert).
        # Use a placeholder pointer trick: we don't have the new run yet, so
        # supersede with itself temporarily, then re-point.
        Run.objects.filter(id=old.id).update(superseded_by=old)

        # Latest master run — DOES contribute.
        latest = _mk_run(self.repo, branch="master", completed_offset=timedelta(hours=0))
        Run.objects.filter(id=old.id).update(superseded_by=latest)
        _mk_snapshot(latest, identifier="canon-a")
        _mk_snapshot(latest, identifier="canon-b")

        result = vr_api.get_baselines_overview(self.repo.id)

        identifiers = sorted(e.identifier for e in result.entries)
        assert identifiers == ["canon-a", "canon-b"]
        assert result.totals.all_snapshots == 2
        assert result.totals.by_run_type == {RunType.STORYBOOK: 2}

    def test_main_branch_treated_same_as_master(self):
        # Some repos use `main`, some use `master`. Both anchor the universe.
        run = _mk_run(self.repo, branch="main")
        _mk_snapshot(run, identifier="m-1")
        _mk_snapshot(run, identifier="m-2")

        result = vr_api.get_baselines_overview(self.repo.id)
        assert sorted(e.identifier for e in result.entries) == ["m-1", "m-2"]

    def test_run_type_appears_in_by_run_type_breakdown(self):
        sb = _mk_run(self.repo, run_type=RunType.STORYBOOK)
        pw = _mk_run(self.repo, run_type=RunType.PLAYWRIGHT)
        _mk_snapshot(sb, identifier="story-1")
        _mk_snapshot(sb, identifier="story-2")
        _mk_snapshot(pw, identifier="pw-1", metadata={"browser": "chromium"})

        result = vr_api.get_baselines_overview(self.repo.id)

        assert result.totals.by_run_type == {RunType.STORYBOOK: 2, RunType.PLAYWRIGHT: 1}
        pw_entry = next(e for e in result.entries if e.identifier == "pw-1")
        assert pw_entry.browser == "chromium"

    def test_thumbnail_hash_flows_through(self):
        run = _mk_run(self.repo)
        artifact = _mk_artifact(self.repo, content_hash="full-x", with_thumbnail="thumb-x")
        _mk_snapshot(run, identifier="with-thumb", artifact=artifact)
        _mk_snapshot(run, identifier="no-thumb")

        result = vr_api.get_baselines_overview(self.repo.id)

        with_thumb = next(e for e in result.entries if e.identifier == "with-thumb")
        no_thumb = next(e for e in result.entries if e.identifier == "no-thumb")
        assert with_thumb.thumbnail_hash == "thumb-x"
        assert with_thumb.width == 320
        assert with_thumb.height == 200
        assert no_thumb.thumbnail_hash is None

    def test_tolerate_counts_respect_30d_and_90d_windows(self):
        run = _mk_run(self.repo)
        _mk_snapshot(run, identifier="flake")

        # 1 tolerate within 30d, 4 within 90d (so 3 are 30-90d old).
        for offset_days in (5, 40, 60, 80):
            ToleratedHash.objects.create(
                repo=self.repo,
                team_id=self.team.id,
                identifier="flake",
                baseline_hash="b",
                alternate_hash=f"a-{offset_days}",
                reason=ToleratedReason.HUMAN,
            )
        # Push backdate.
        ToleratedHash.objects.filter(repo=self.repo, identifier="flake").update(
            created_at=timezone.now() - timedelta(days=5),  # everything to 5d for first pass
        )
        # Now individually backdate the older 3.
        rows = list(ToleratedHash.objects.filter(repo=self.repo, identifier="flake").order_by("alternate_hash"))
        ToleratedHash.objects.filter(id=rows[0].id).update(created_at=timezone.now() - timedelta(days=40))
        ToleratedHash.objects.filter(id=rows[1].id).update(created_at=timezone.now() - timedelta(days=60))
        ToleratedHash.objects.filter(id=rows[2].id).update(created_at=timezone.now() - timedelta(days=80))
        # rows[3] stays at 5d.

        result = vr_api.get_baselines_overview(self.repo.id)
        entry = next(e for e in result.entries if e.identifier == "flake")

        assert entry.tolerate_count_30d == 1
        assert entry.tolerate_count_90d == 4
        assert result.totals.recently_tolerated == 1  # ≥1 in last 30d
        assert result.totals.frequently_tolerated == 1  # ≥3 in last 90d

    def test_active_quarantine_counts_but_expired_does_not(self):
        run = _mk_run(self.repo)
        _mk_snapshot(run, identifier="active")
        _mk_snapshot(run, identifier="expired")
        _mk_snapshot(run, identifier="future")

        # No expires_at = active forever
        QuarantinedIdentifier.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier="active",
            run_type=RunType.STORYBOOK,
            reason="flaky",
        )
        # expired (past expires_at) — should NOT count
        QuarantinedIdentifier.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier="expired",
            run_type=RunType.STORYBOOK,
            reason="old",
            expires_at=timezone.now() - timedelta(days=1),
        )
        # Future expires_at — counts
        QuarantinedIdentifier.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier="future",
            run_type=RunType.STORYBOOK,
            reason="upcoming",
            expires_at=timezone.now() + timedelta(days=7),
        )

        result = vr_api.get_baselines_overview(self.repo.id)

        by_id = {e.identifier: e.is_quarantined for e in result.entries}
        assert by_id == {"active": True, "expired": False, "future": True}
        assert result.totals.currently_quarantined == 2

    def test_sparkline_buckets_by_classification(self):
        # Universe row (latest baseline) — counts as 1 clean in sparkline.
        latest = _mk_run(self.repo)
        _mk_snapshot(latest, identifier="story")

        # Separate history runs (different branches so the unique constraint
        # on (run, identifier) doesn't bite). Each contributes one bucketed
        # entry to the 30-day window.
        clean_run = _mk_run(self.repo, branch="pr-clean", completed_offset=timedelta(days=1))
        _mk_snapshot(clean_run, identifier="story", result=SnapshotResult.UNCHANGED)

        changed_run = _mk_run(self.repo, branch="pr-changed", completed_offset=timedelta(days=2))
        _mk_snapshot(changed_run, identifier="story", result=SnapshotResult.CHANGED, created_offset=timedelta(days=2))

        quar_run = _mk_run(self.repo, branch="pr-quar", completed_offset=timedelta(days=3))
        _mk_snapshot(
            quar_run,
            identifier="story",
            result=SnapshotResult.UNCHANGED,
            is_quarantined=True,
            created_offset=timedelta(days=3),
        )

        tol = ToleratedHash.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            identifier="story",
            baseline_hash="b",
            alternate_hash="a",
            reason=ToleratedReason.HUMAN,
        )
        tol_run = _mk_run(self.repo, branch="pr-tol", completed_offset=timedelta(days=4))
        _mk_snapshot(
            tol_run,
            identifier="story",
            result=SnapshotResult.UNCHANGED,
            tolerated_match=tol,
            created_offset=timedelta(days=4),
        )

        result = vr_api.get_baselines_overview(self.repo.id)
        entry = next(e for e in result.entries if e.identifier == "story")
        assert len(entry.sparkline) == BASELINE_SPARKLINE_DAYS

        totals = {
            "clean": sum(d.clean for d in entry.sparkline),
            "tolerated": sum(d.tolerated for d in entry.sparkline),
            "changed": sum(d.changed for d in entry.sparkline),
            "quarantined": sum(d.quarantined for d in entry.sparkline),
        }
        # The universe-anchor snapshot itself counts once as clean (it's the
        # most recent UNCHANGED). Plus one explicit "clean" history row.
        assert totals == {"clean": 2, "tolerated": 1, "changed": 1, "quarantined": 1}

    def test_truncation_at_cap(self):
        # Use a tiny cap for speed. logic.get_baselines_overview imports the
        # constant lazily, so patching contracts is enough.
        run = _mk_run(self.repo)
        for i in range(7):
            _mk_snapshot(run, identifier=f"id-{i:02d}")

        with patch("products.visual_review.backend.facade.contracts.BASELINE_OVERVIEW_MAX_ENTRIES", 5):
            result = vr_api.get_baselines_overview(self.repo.id)

        assert len(result.entries) == 5
        assert result.truncated is True
        # all_snapshots total reflects the full universe even when truncated
        assert result.totals.all_snapshots == 7

    def test_endpoint_returns_serialized_overview(self):
        run = _mk_run(self.repo)
        artifact = _mk_artifact(self.repo, content_hash="h1", with_thumbnail="t1")
        _mk_snapshot(run, identifier="card-one", artifact=artifact, metadata={"browser": "chromium"})
        _mk_snapshot(run, identifier="card-two")

        url = f"/api/projects/{self.team.id}/visual_review/repos/{self.repo.id}/baselines/"
        response = self.client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert "totals" in data
        assert data["truncated"] is False
        assert {e["identifier"] for e in data["entries"]} == {"card-one", "card-two"}
        first = next(e for e in data["entries"] if e["identifier"] == "card-one")
        assert first["thumbnail_hash"] == "t1"
        assert first["browser"] == "chromium"
        assert len(first["sparkline"]) == BASELINE_SPARKLINE_DAYS

    def test_endpoint_404_for_unknown_repo(self):
        url = f"/api/projects/{self.team.id}/visual_review/repos/{uuid4()}/baselines/"
        response = self.client.get(url)
        assert response.status_code == 404

    def test_truncation_constant_is_a_safe_default(self):
        # Sanity guard — if someone bumps the cap without updating clients, this
        # test reminds them. ~5000 fits the FE budget (≈600 KB gzipped).
        assert 1000 <= BASELINE_OVERVIEW_MAX_ENTRIES <= 10000
