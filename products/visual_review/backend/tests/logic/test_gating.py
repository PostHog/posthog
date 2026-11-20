"""Unit tests for logic/gating.py — Quarantine stamping and resolution accounting."""

from datetime import timedelta

import pytest
import time_machine

from django.utils import timezone

from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import RunType
from products.visual_review.backend.logic import approvals, artifact_store, github_api, quarantine, repos, runs
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

    @pytest.mark.parametrize(
        ("lifted_at_sha", "merge_base", "superseded", "expect_quarantined"),
        [
            (None, None, False, False),
            ("lift", "lift", False, False),
            ("lift", "older", False, True),
            ("lift", None, False, True),
            ("lift", "older", True, False),
        ],
        ids=[
            "legacy-lift-without-sha",
            "run-contains-lift",
            "branch-forked-before-lift",
            "ancestry-unknown",
            "lift-superseded-by-newer-quarantine",
        ],
    )
    def test_unquarantine_clears_flag_on_approve(
        self, repo, team, user, mocker, lifted_at_sha, merge_base, superseded, expect_quarantined
    ):
        from products.visual_review.backend.models import QuarantinedIdentifier

        mocker.patch.object(github_api, "default_branch_head_sha", return_value=lifted_at_sha or "lift")
        mocker.patch.object(github_api, "get_github_integration_for_repo")
        mocker.patch.object(github_api, "_get_merge_base_sha", return_value=merge_base)

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
        if lifted_at_sha is None:
            QuarantinedIdentifier.objects.filter(identifier="Button-primary").update(lifted_at_sha=None)
        if superseded:
            QuarantinedIdentifier.objects.create(
                repo=repo,
                team_id=team.id,
                identifier="Button-primary",
                run_type=RunType.STORYBOOK,
                reason="flaky again",
                expires_at=timezone.now(),
            )

        # Finalize the run — _stamp_quarantine re-evaluates
        approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        snapshot.refresh_from_db()
        assert snapshot.is_quarantined is expect_quarantined

    def _lift_history(self, repo, team, mocker):
        from products.visual_review.backend.models import QuarantinedIdentifier

        # Each commit maps to the commits in its history. m1 to m5 are successive default-branch heads.
        history = {f"m{n}": {f"m{k}" for k in range(1, n + 1)} for n in range(1, 6)}
        history["branch-from-m2"] = {"m1", "m2", "branch-from-m2"}
        requests: list[tuple[str, str]] = []

        def merge_base(github, repo_full_name, base, head):
            requests.append((base, head))
            return base if base in history[head] else "m0"

        mocker.patch.object(github_api, "get_github_integration_for_repo")
        mocker.patch.object(github_api, "_get_merge_base_sha", side_effect=merge_base)

        now = timezone.now()
        for identifier, lift_commit, hours_ago in [("Story-a", "m1", 3), ("Story-b", "m2", 2), ("Story-c", "m3", 1)]:
            QuarantinedIdentifier.objects.create(
                repo=repo,
                team_id=team.id,
                identifier=identifier,
                run_type=RunType.STORYBOOK,
                reason="flaky",
                expires_at=now - timedelta(hours=hours_ago),
                lifted_at_sha=lift_commit,
            )
        return now, requests

    def _run_at_commit(self, repo, commit_sha):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha=commit_sha,
                branch="feature",
                pr_number=1,
                snapshots=[
                    SnapshotManifestItem(identifier=identifier, content_hash=f"h-{identifier}")
                    for identifier in ["Story-a", "Story-b", "Story-c"]
                ],
            ),
            team_id=repo.team_id,
        )
        return run

    @pytest.mark.parametrize(
        ("run_commit", "expect_lifted_after"),
        [("m4", set()), ("branch-from-m2", {"Story-c"})],
        ids=["run-contains-every-lift", "branch-forked-before-newest-lift"],
    )
    def test_lift_scope_follows_the_run_history(self, repo, team, mocker, run_commit, expect_lifted_after):
        now, _ = self._lift_history(repo, team, mocker)

        run = self._run_at_commit(repo, run_commit)

        assert quarantine.identifiers_lifted_after_commit(run, now=now) == expect_lifted_after

    def test_lift_scope_asks_github_about_a_next_day_default_branch_run_once(self, repo, team, mocker):
        with time_machine.travel(timezone.now(), tick=False) as clock:
            now, requests = self._lift_history(repo, team, mocker)
            quarantine.identifiers_lifted_after_commit(self._run_at_commit(repo, "m4"), now=now)
            requests.clear()
            clock.shift(timedelta(days=1))

            next_run = self._run_at_commit(repo, "m5")
            assert quarantine.identifiers_lifted_after_commit(next_run, now=now + timedelta(days=1)) == set()
        assert requests == [("m3", "m5")]

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
