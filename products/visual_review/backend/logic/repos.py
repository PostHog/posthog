"""Repo CRUD."""

from __future__ import annotations

from uuid import UUID

from ..facade.contracts import UpdateRepoInput
from ..models import Repo
from . import errors


def get_repo(repo_id: UUID, team_id: int) -> Repo:
    try:
        return Repo.objects.get(id=repo_id, team_id=team_id)
    except Repo.DoesNotExist as e:
        raise errors.RepoNotFoundError(f"Repo {repo_id} not found") from e


def list_repos_for_team(team_id: int) -> list[Repo]:
    return list(Repo.objects.filter(team_id=team_id).order_by("-created_at"))


def create_repo(team_id: int, repo_external_id: int, repo_full_name: str) -> Repo:
    return Repo.objects.create(
        team_id=team_id,
        repo_external_id=repo_external_id,
        repo_full_name=repo_full_name,
    )


def update_repo(input: UpdateRepoInput, team_id: int) -> Repo:
    repo = get_repo(input.repo_id, team_id)
    if input.baseline_file_paths is not None:
        repo.baseline_file_paths = input.baseline_file_paths
    if input.enable_pr_comments is not None:
        repo.enable_pr_comments = input.enable_pr_comments
    repo.save()
    return repo
