"""Unit tests for logic/repos.py — Repo CRUD."""

import pytest

from products.visual_review.backend.logic import errors, repos
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestProjectOperations:
    def test_create_repo(self, team):
        repo = repos.create_repo(team_id=team.id, repo_external_id=12345, repo_full_name="org/my-repo")

        assert repo.team_id == team.id
        assert repo.repo_external_id == 12345
        assert repo.repo_full_name == "org/my-repo"

    def test_get_repo(self, team):
        repo = repos.create_repo(team_id=team.id, repo_external_id=11111, repo_full_name="org/test")

        retrieved = repos.get_repo(repo.id, team_id=team.id)

        assert retrieved.id == repo.id
        assert retrieved.repo_full_name == "org/test"

    def test_get_repo_not_found(self, team):
        import uuid

        with pytest.raises(errors.RepoNotFoundError):
            repos.get_repo(uuid.uuid4(), team_id=team.id)

    def test_list_repos_for_team(self, team):
        repos.create_repo(team_id=team.id, repo_external_id=111, repo_full_name="org/first")
        repos.create_repo(team_id=team.id, repo_external_id=222, repo_full_name="org/second")

        projects = repos.list_repos_for_team(team.id)

        assert len(projects) == 2
        names = {p.repo_full_name for p in projects}
        assert names == {"org/first", "org/second"}
