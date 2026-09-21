"""Unit tests for logic/run_queries.py — Run and snapshot lookups."""

import pytest

from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import RunType
from products.visual_review.backend.logic import repos, run_queries, runs
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestGetRunSnapshots:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    def test_get_run_snapshots(self, repo):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[
                    SnapshotManifestItem(identifier="A-component", content_hash="h1"),
                    SnapshotManifestItem(identifier="B-component", content_hash="h2"),
                    SnapshotManifestItem(identifier="C-component", content_hash="h3"),
                ],
                baseline_hashes={},
            ),
            team_id=repo.team_id,
        )

        snapshots = run_queries.get_run_snapshots(run.id)

        assert len(snapshots) == 3
        # Should be ordered by identifier
        assert [s.identifier for s in snapshots] == ["A-component", "B-component", "C-component"]
