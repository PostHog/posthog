"""Unit tests for logic/quarantine.py — Quarantined identifiers."""

import pytest

from django.utils import timezone

from products.visual_review.backend.facade.enums import RunStatus, RunType
from products.visual_review.backend.logic import quarantine, repos
from products.visual_review.backend.models import Repo, Run
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestQuarantineIdentifier:
    """Coverage for `quarantine.quarantine_identifier` — especially the new
    `source_run_id` behavior (valid run is stored, foreign run is dropped)."""

    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=88888, repo_full_name="org/test-source-run")

    def _mk_run(self, repo: Repo, branch: str = "main") -> Run:
        return Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            run_type=RunType.STORYBOOK,
            branch=branch,
            commit_sha="abc123",
            status=RunStatus.COMPLETED,
            completed_at=timezone.now(),
        )

    def test_stores_valid_source_run(self, repo, team, user):
        from products.visual_review.backend.models import QuarantinedIdentifier

        run = self._mk_run(repo)
        entry = quarantine.quarantine_identifier(
            repo_id=repo.id,
            identifier="flake",
            run_type=RunType.STORYBOOK,
            reason="non-deterministic",
            user_id=user.id,
            team_id=team.id,
            source_run_id=run.id,
        )
        # Returned row points at the source run …
        assert entry.source_run_id == run.id
        # … and the persisted row agrees.
        persisted = QuarantinedIdentifier.objects.get(id=entry.id)
        assert persisted.source_run_id == run.id

    def test_drops_source_run_from_another_team(self, repo, team, user):
        """A `source_run_id` from a run that doesn't belong to this team/repo
        is silently dropped — the quarantine still gets created, just without
        the cross-team pointer."""
        from posthog.models.team.team import Team

        # Sibling team in the same org with its own repo + run.
        other_team = Team.objects.create(organization=team.organization, name="other")
        other_repo = repos.create_repo(team_id=other_team.id, repo_external_id=12121, repo_full_name="org/other-repo")
        foreign_run = Run.objects.create(
            team_id=other_team.id,
            repo=other_repo,
            run_type=RunType.STORYBOOK,
            branch="main",
            commit_sha="xyz789",
            status=RunStatus.COMPLETED,
            completed_at=timezone.now(),
        )

        entry = quarantine.quarantine_identifier(
            repo_id=repo.id,
            identifier="flake",
            run_type=RunType.STORYBOOK,
            reason="non-deterministic",
            user_id=user.id,
            team_id=team.id,
            source_run_id=foreign_run.id,
        )
        assert entry.source_run_id is None

    def test_omitting_source_run_leaves_it_null(self, repo, team, user):
        entry = quarantine.quarantine_identifier(
            repo_id=repo.id,
            identifier="flake",
            run_type=RunType.STORYBOOK,
            reason="non-deterministic",
            user_id=user.id,
            team_id=team.id,
        )
        assert entry.source_run_id is None
