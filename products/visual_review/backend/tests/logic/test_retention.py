"""Unit tests for logic/retention.py, the run and artifact retention sweep."""

from datetime import timedelta

import pytest

from django.utils import timezone

from products.visual_review.backend.facade.enums import RunStatus, RunType, ToleratedReason
from products.visual_review.backend.logic import artifact_store, repos, retention
from products.visual_review.backend.models import Artifact, QuarantinedIdentifier, Run, RunSnapshot, ToleratedHash
from products.visual_review.backend.tasks.tasks import sweep_visual_review_retention
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRetentionSweep:
    @pytest.fixture(autouse=True)
    def stub_object_delete(self, mocker, settings):
        # No test may reach S3. The setting is forced on so the storage layer
        # takes the delete path regardless of how the suite is configured.
        settings.OBJECT_STORAGE_ENABLED = True
        return mocker.patch(
            "products.visual_review.backend.storage.object_storage.delete_objects",
            return_value=[],
        )

    @pytest.fixture
    def now(self):
        return timezone.now()

    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    @pytest.fixture
    def other_repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=88888, repo_full_name="org/other")

    def _run(
        self,
        repo,
        now,
        *,
        age_days: int,
        branch: str = "feature/x",
        run_type: str = RunType.STORYBOOK,
        pr_number: int | None = 7,
        superseded_by: Run | None = None,
        is_partial: bool = False,
        status: str = RunStatus.COMPLETED,
    ) -> Run:
        run = Run.objects.create(
            repo=repo,
            team_id=repo.team_id,
            branch=branch,
            run_type=run_type,
            commit_sha="abc123",
            pr_number=pr_number,
            superseded_by=superseded_by,
            is_partial=is_partial,
            status=status,
        )
        # created_at is auto_now_add, so the age has to be written afterwards.
        Run.objects.filter(id=run.id).update(created_at=now - timedelta(days=age_days))
        return run

    def _artifact(self, repo, now, *, content_hash: str, age_days: int, thumbnail: Artifact | None = None) -> Artifact:
        artifact, _ = artifact_store.get_or_create_artifact(
            repo_id=repo.id,
            content_hash=content_hash,
            storage_path=f"visual_review/{content_hash}",
        )
        if thumbnail is not None:
            artifact.thumbnail = thumbnail
            artifact.save(update_fields=["thumbnail"])
        Artifact.objects.filter(id=artifact.id).update(created_at=now - timedelta(days=age_days))
        return artifact

    @pytest.mark.parametrize(
        ("branch", "pr_number", "age_days", "survives"),
        [
            ("feature/x", 7, 31, False),
            ("feature/x", 7, 29, True),
            ("master", None, 31, True),
            ("master", None, 181, False),
            ("feature/x", None, 31, True),
            ("feature/x", None, 181, False),
        ],
    )
    def test_superseded_run_retention_depends_on_branch(self, branch, pr_number, age_days, survives, repo, now):
        latest = self._run(repo, now, age_days=age_days, branch=branch, pr_number=pr_number)
        superseded = self._run(repo, now, age_days=age_days, branch=branch, pr_number=pr_number, superseded_by=latest)

        retention.sweep_repo(repo, now=now)

        assert Run.objects.filter(id=superseded.id).exists() is survives
        assert Run.objects.filter(id=latest.id).exists()

    def test_default_branch_latest_run_survives_any_age(self, repo, now):
        latest = self._run(repo, now, age_days=400, branch="master", pr_number=None)

        result = retention.sweep_repo(repo, now=now)

        assert result.runs_deleted == 0
        assert Run.objects.filter(id=latest.id).exists()

    def test_quiet_branch_group_goes_in_one_sweep(self, repo, now):
        latest = self._run(repo, now, age_days=91)
        superseded = self._run(repo, now, age_days=100, superseded_by=latest)
        self._run(repo, now, age_days=1, branch="feature/y", pr_number=8)

        result = retention.sweep_repo(repo, now=now)

        assert result.runs_deleted == 2
        assert not Run.objects.filter(id__in=[latest.id, superseded.id]).exists()

    def test_quiet_branch_keeps_the_newest_completed_run_of_a_run_type(self, repo, now):
        latest = self._run(repo, now, age_days=91)

        assert retention.sweep_repo(repo, now=now).runs_deleted == 0
        assert Run.objects.filter(id=latest.id).exists()

        self._run(repo, now, age_days=2, branch="feature/z", pr_number=9, is_partial=True)

        assert retention.sweep_repo(repo, now=now).runs_deleted == 0

        self._run(repo, now, age_days=1, branch="feature/y", pr_number=8)

        assert retention.sweep_repo(repo, now=now).runs_deleted == 1
        assert not Run.objects.filter(id=latest.id).exists()

    def test_quiet_branch_kept_when_another_run_type_is_recent(self, repo, now):
        stale_latest = self._run(repo, now, age_days=91, run_type=RunType.STORYBOOK)
        self._run(repo, now, age_days=2, run_type=RunType.PLAYWRIGHT)

        retention.sweep_repo(repo, now=now)

        assert Run.objects.filter(id=stale_latest.id).exists()

    def test_supersession_chain_goes_oldest_first_in_one_sweep(self, repo, now):
        latest = self._run(repo, now, age_days=5)
        second = self._run(repo, now, age_days=40, superseded_by=latest)
        first = self._run(repo, now, age_days=50, superseded_by=second)

        result = retention.sweep_repo(repo, now=now)

        assert result.runs_deleted == 2
        assert not Run.objects.filter(id__in=[first.id, second.id]).exists()
        # unique_latest_run_per_group allows one run per group with a NULL
        # superseded_by. A batched delete sets the surviving older link to NULL
        # while the group's latest run is still there, which raises
        # IntegrityError on that index.
        assert (
            Run.objects.filter(
                repo=repo, branch="feature/x", run_type=RunType.STORYBOOK, superseded_by__isnull=True
            ).count()
            == 1
        )

    @pytest.mark.parametrize(
        ("model", "extra_fields"),
        [
            (
                ToleratedHash,
                {"baseline_hash": "base1", "alternate_hash": "alt1", "reason": ToleratedReason.HUMAN},
            ),
            (QuarantinedIdentifier, {"run_type": RunType.STORYBOOK, "reason": "flaky in CI"}),
        ],
    )
    def test_audit_rows_outlive_the_run_that_created_them(self, model, extra_fields, repo, now):
        latest = self._run(repo, now, age_days=91)
        superseded = self._run(repo, now, age_days=100, superseded_by=latest)
        row = model.objects.create(
            repo=repo,
            team_id=repo.team_id,
            identifier="Button",
            source_run=superseded,
            **extra_fields,
        )

        retention.sweep_repo(repo, now=now)

        row.refresh_from_db()
        assert row.source_run_id is None

    def test_run_cap_bounds_one_invocation(self, repo, now, monkeypatch):
        monkeypatch.setattr(retention, "MAX_RUNS_PER_SWEEP", 1)
        latest = self._run(repo, now, age_days=91)
        self._run(repo, now, age_days=110, superseded_by=latest)
        self._run(repo, now, age_days=100, superseded_by=latest)

        result = retention.sweep_repo(repo, now=now)

        assert result.runs_deleted == 1
        assert Run.objects.filter(id=latest.id).exists()
        assert Run.objects.filter(superseded_by=latest).count() == 1

    def test_deleting_a_run_frees_the_artifacts_only_it_referenced(self, repo, now):
        latest = self._run(repo, now, age_days=91)
        superseded = self._run(repo, now, age_days=100, superseded_by=latest)
        artifact = self._artifact(repo, now, content_hash="current1", age_days=100)
        RunSnapshot.objects.create(run=superseded, team_id=repo.team_id, identifier="Button", current_artifact=artifact)

        result = retention.sweep_repo(repo, now=now)

        assert not RunSnapshot.objects.filter(run_id=superseded.id).exists()
        assert result.artifacts_deleted == 1
        assert not Artifact.objects.filter(id=artifact.id).exists()

    @pytest.mark.parametrize(("age_days", "survives"), [(3, True), (8, False)])
    def test_orphaned_artifact_waits_out_the_grace_period(self, age_days, survives, repo, now):
        artifact = self._artifact(repo, now, content_hash="orphan1", age_days=age_days)

        retention.sweep_repo(repo, now=now)

        assert Artifact.objects.filter(id=artifact.id).exists() is survives

    @pytest.mark.parametrize(
        "field",
        ["current_artifact", "baseline_artifact", "diff_artifact", "current_hash", "baseline_hash"],
    )
    def test_artifact_referenced_by_a_snapshot_is_kept(self, field, repo, now):
        run = self._run(repo, now, age_days=1)
        artifact = self._artifact(repo, now, content_hash="referenced1", age_days=30)
        reference = artifact.content_hash if field.endswith("_hash") else artifact
        RunSnapshot.objects.create(run=run, team_id=repo.team_id, identifier="Button", **{field: reference})

        result = retention.sweep_repo(repo, now=now)

        assert result.artifacts_deleted == 0
        assert Artifact.objects.filter(id=artifact.id).exists()

    @pytest.mark.parametrize("field", ["current_hash", "baseline_hash"])
    def test_hash_reference_from_another_repo_does_not_keep_an_artifact(self, field, repo, other_repo, now):
        artifact = self._artifact(repo, now, content_hash="shared1", age_days=30)
        run = self._run(other_repo, now, age_days=1)
        RunSnapshot.objects.create(run=run, team_id=repo.team_id, identifier="Button", **{field: artifact.content_hash})

        result = retention.sweep_repo(repo, now=now)

        assert result.artifacts_deleted == 1
        assert not Artifact.objects.filter(id=artifact.id).exists()

    def test_thumbnail_is_collected_one_sweep_after_its_parent(self, repo, now):
        thumbnail = self._artifact(repo, now, content_hash="thumb1", age_days=30)
        parent = self._artifact(repo, now, content_hash="parent1", age_days=30, thumbnail=thumbnail)

        assert retention.sweep_repo(repo, now=now).artifacts_deleted == 1
        assert not Artifact.objects.filter(id=parent.id).exists()
        assert Artifact.objects.filter(id=thumbnail.id).exists()

        assert retention.sweep_repo(repo, now=now).artifacts_deleted == 1
        assert not Artifact.objects.filter(id=thumbnail.id).exists()

    def test_a_failed_object_delete_leaks_the_object(self, repo, now, stub_object_delete):
        artifact = self._artifact(repo, now, content_hash="orphan2", age_days=30)
        stub_object_delete.return_value = [artifact.storage_path]

        result = retention.sweep_repo(repo, now=now)

        assert result.artifacts_deleted == 1
        assert result.objects_leaked == 1
        assert not Artifact.objects.filter(id=artifact.id).exists()

    def test_artifact_cap_bounds_one_invocation(self, repo, now, monkeypatch):
        monkeypatch.setattr(retention, "MAX_ARTIFACTS_PER_SWEEP", 1)
        self._artifact(repo, now, content_hash="orphan3", age_days=30)
        self._artifact(repo, now, content_hash="orphan4", age_days=30)

        result = retention.sweep_repo(repo, now=now)

        assert result.artifacts_deleted == 1
        assert Artifact.objects.filter(repo_id=repo.id).count() == 1

    def test_sweeping_one_repo_leaves_another_repo_alone(self, repo, other_repo, now):
        kept_latest = self._run(other_repo, now, age_days=200)
        kept_superseded = self._run(other_repo, now, age_days=300, superseded_by=kept_latest)
        kept_artifact = self._artifact(other_repo, now, content_hash="otherorphan", age_days=30)
        self._artifact(repo, now, content_hash="orphan5", age_days=30)

        result = retention.sweep_repo(repo, now=now)

        assert result.runs_deleted == 0
        assert result.artifacts_deleted == 1
        assert Run.objects.filter(id__in=[kept_latest.id, kept_superseded.id]).count() == 2
        assert Artifact.objects.filter(id=kept_artifact.id).exists()

    def test_task_sweeps_every_repo_when_one_of_them_fails(self, repo, other_repo, mocker):
        sweep_repo = mocker.patch.object(
            retention,
            "sweep_repo",
            side_effect=[
                Exception("boom"),
                retention.RetentionSweepResult(runs_deleted=0, artifacts_deleted=0, objects_leaked=0),
            ],
        )
        capture_exception = mocker.patch("products.visual_review.backend.tasks.tasks.capture_exception")

        sweep_visual_review_retention()

        assert {call.args[0].id for call in sweep_repo.call_args_list} == {repo.id, other_repo.id}
        assert capture_exception.call_count == 1

    def test_task_stops_sweeping_repos_when_the_time_budget_is_gone(self, repo, other_repo, mocker):
        mocker.patch.object(retention, "SWEEP_TIME_BUDGET_SECONDS", 0)
        sweep_repo = mocker.patch.object(retention, "sweep_repo")

        sweep_visual_review_retention()

        assert sweep_repo.call_count == 0
