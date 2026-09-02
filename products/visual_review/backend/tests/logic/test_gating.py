"""Unit tests for logic/gating.py — Quarantine stamping and resolution accounting."""

import pytest

from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import RunType
from products.visual_review.backend.logic import approvals, artifact_store, quarantine, repos, runs
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestQuarantineStamping:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99996, repo_full_name="org/test-quarantine")

    def _create_completed_run(self, repo, mocker, identifiers_and_hashes, baseline=None):
        """Create a run, classify against baseline, and finalize it.

        identifiers_and_hashes: list of (identifier, content_hash)
        baseline: dict of identifier -> baseline_hash (for _resolve_baselines mock)
        """
        snapshots = [SnapshotManifestItem(identifier=ident, content_hash=h) for ident, h in identifiers_and_hashes]
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=1,
                snapshots=snapshots,
            ),
            team_id=repo.team_id,
        )

        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=(baseline or {}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        return run

    def test_finish_processing_stamps_quarantined_snapshots(self, repo, team, mocker):
        from products.visual_review.backend.models import QuarantinedIdentifier

        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[
                ("Button-primary", "h1"),
                ("Button-secondary", "h2"),
                ("Card-default", "h3"),
            ],
            baseline={"Button-primary": "old1", "Button-secondary": "old2", "Card-default": "old3"},
        )

        # Quarantine one identifier
        QuarantinedIdentifier.objects.create(
            repo=repo,
            team_id=team.id,
            identifier="Button-primary",
            run_type=RunType.STORYBOOK,
            reason="flaky",
        )

        runs.finish_processing(run.id)

        snapshots = {s.identifier: s for s in run.snapshots.all()}
        assert snapshots["Button-primary"].is_quarantined is True
        assert snapshots["Button-secondary"].is_quarantined is False
        assert snapshots["Card-default"].is_quarantined is False

    def test_unquarantine_clears_flag_on_approve(self, repo, team, user, mocker):
        from products.visual_review.backend.models import QuarantinedIdentifier

        # Create quarantine entry
        QuarantinedIdentifier.objects.create(
            repo=repo,
            team_id=team.id,
            identifier="Button-primary",
            run_type=RunType.STORYBOOK,
            reason="flaky",
        )

        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="h1", storage_path="p/h1")
        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button-primary", "h1")],
            baseline={"Button-primary": "old1"},
        )

        runs.finish_processing(run.id)
        snapshot = run.snapshots.get(identifier="Button-primary")
        assert snapshot.is_quarantined is True

        # Unquarantine the identifier
        quarantine.unquarantine_identifier(
            repo_id=repo.id, identifier="Button-primary", run_type=RunType.STORYBOOK, team_id=team.id
        )

        # Finalize the run — _stamp_quarantine re-evaluates
        approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        snapshot.refresh_from_db()
        assert snapshot.is_quarantined is False

    def test_quarantine_excludes_from_changed_count(self, repo, team, mocker):
        from products.visual_review.backend.models import QuarantinedIdentifier

        # Quarantine one identifier before finalization
        QuarantinedIdentifier.objects.create(
            repo=repo,
            team_id=team.id,
            identifier="Button-primary",
            run_type=RunType.STORYBOOK,
            reason="flaky",
        )

        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[
                ("Button-primary", "h1"),
                ("Button-secondary", "h2"),
                ("Card-new", "h3"),
            ],
            baseline={"Button-primary": "old1", "Button-secondary": "old2"},
        )

        processed = runs.finish_processing(run.id)

        # Button-primary is quarantined — should not count toward changed
        # Button-secondary is changed (not quarantined), Card-new is new (not quarantined)
        assert processed.changed_count == 1  # only Button-secondary
        assert processed.new_count == 1  # only Card-new
