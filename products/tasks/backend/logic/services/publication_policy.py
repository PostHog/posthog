"""Fail-closed policy checks immediately before the server-side GitHub write."""

from __future__ import annotations

import re
from datetime import datetime

from django.utils import timezone

from products.tasks.backend.facade.staged_execution import InvalidStagedTaskBindingError
from products.tasks.backend.logic.services.run_actor import user_has_current_team_access
from products.tasks.backend.logic.services.staged_task_runs import validate_staged_repository_grant
from products.tasks.backend.models import TaskDraftPublication, TaskRun

_SERVER_BRANCH = re.compile(r"^codex/tasks-draft-[0-9a-f]{32}$")


class PublicationPolicyError(ValueError):
    pass


def validate_publication_metadata(
    *, head_branch: str, starts_before: datetime, expires_at: datetime, already_started: bool = False
) -> None:
    if not _SERVER_BRANCH.fullmatch(head_branch):
        raise PublicationPolicyError("Draft publication branch is not server-owned")
    now = timezone.now()
    if (not already_started and now >= starts_before) or expires_at <= now or starts_before >= expires_at:
        raise PublicationPolicyError("Draft publication is outside its reservation window")


def validate_bundle_acceptance_authority(publication: TaskDraftPublication) -> None:
    staged_run = publication.staged_run
    task = staged_run.task
    if (
        publication.status not in {TaskDraftPublication.Status.PENDING, TaskDraftPublication.Status.UNKNOWN}
        or staged_run.cancelled_at is not None
        or staged_run.capabilities_revoked_at is not None
        or staged_run.execution_run is None
        or staged_run.execution_run.status != TaskRun.Status.COMPLETED
        or task.created_by is None
        or not user_has_current_team_access(task.created_by, task.team)
    ):
        raise PublicationPolicyError("Draft publication is no longer authorized")
    if (
        publication.repository != staged_run.repository
        or publication.base_sha != staged_run.base_sha
        or publication.base_branch != staged_run.base_branch
        or publication.github_integration_id != staged_run.github_integration_id
        or publication.github_installation_id != staged_run.github_installation_id
    ):
        raise PublicationPolicyError("Draft publication no longer matches the staged repository binding")
    if not all((publication.repository, publication.github_integration_id, publication.github_installation_id)):
        raise PublicationPolicyError("Draft publication has no authoritative GitHub binding")
    validate_publication_metadata(
        head_branch=publication.head_branch,
        starts_before=publication.starts_before,
        expires_at=publication.expires_at,
        already_started=publication.claimed_at is not None,
    )
    try:
        validate_staged_repository_grant(
            team_id=publication.team_id,
            repository=publication.repository,
            github_integration_id=publication.github_integration_id,
            github_installation_id=publication.github_installation_id,
        )
    except InvalidStagedTaskBindingError as err:
        raise PublicationPolicyError("Draft publication repository grant is no longer authorized") from err


def validate_publication_authority(publication: TaskDraftPublication) -> None:
    """Revalidate all mutable authorization immediately before egress."""
    validate_bundle_acceptance_authority(publication)
    if not all(
        (
            publication.bundle_storage_ref,
            publication.bundle_sha256,
            publication.bundle_size,
            publication.bundle_head_sha,
            publication.bundle_base_tree_sha,
            publication.bundle_head_tree_sha,
            publication.gate_summary_ref,
        )
    ) or publication.gate_summary != {"git_diff_check": "passed"}:
        raise PublicationPolicyError("Draft publication has no validated bundle and protected gate result")
