"""Durable lifecycle operations for staged Task execution."""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from typing import NoReturn, cast, get_args
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from posthog.models import Team
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.user import User
from posthog.temporal.oauth import McpScopePreset, PosthogMcpScopes

from products.tasks.backend.facade.staged_execution import (
    AdvancedStagedTask,
    AdvanceStagedTaskInput,
    CreatedStagedTask,
    CreateStagedTaskInput,
    InvalidStagedTaskBindingError,
    StagedCapabilityManifest,
    StagedRepositoryBinding,
)
from products.tasks.backend.logic.services.run_actor import user_has_current_team_access
from products.tasks.backend.models import Task, TaskRun, TaskStagedRun

_MANIFEST_VERSION = 1
_MAX_OUTPUT_SCHEMA_BYTES = 100_000
_REPOSITORY_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_COMMIT_SHA = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


@dataclass(frozen=True)
class StagedExecutionBinding:
    repository: str | None
    base_sha: str | None
    github_integration_id: int | None
    github_installation_id: str | None
    mcp_scope_preset: str
    disabled_tools: tuple[str, ...]
    phase: str


def get_staged_execution_binding(run_id: str) -> StagedExecutionBinding | None:
    """Resolve execution authority from the lifecycle record, never mutable run state."""
    staged_run = (
        TaskStagedRun.objects.unscoped()
        .select_related("task", "task__created_by")
        .filter(Q(analysis_run_id=run_id) | Q(execution_run_id=run_id))
        .first()
    )
    if staged_run is None:
        return None
    if staged_run.task.created_by is None or not user_has_current_team_access(
        staged_run.task.created_by, staged_run.team
    ):
        _invalid_binding("Staged task actor no longer has team access")
    is_execution = str(staged_run.execution_run_id) == run_id
    manifest = staged_run.execution_manifest if is_execution else staged_run.analysis_manifest
    if (
        staged_run.cancelled_at is not None
        or staged_run.capabilities_revoked_at is not None
        or not isinstance(manifest, dict)
        or manifest.get("version") != _MANIFEST_VERSION
        or manifest.get("phase") != ("execution" if is_execution else "analysis")
        or not isinstance(manifest.get("mcp_scope_preset"), str)
        or not isinstance(manifest.get("disabled_tools"), list)
        or not all(isinstance(tool, str) for tool in manifest["disabled_tools"])
    ):
        _invalid_binding("Staged task execution binding is invalid")
    return StagedExecutionBinding(
        repository=staged_run.repository,
        base_sha=staged_run.base_sha,
        github_integration_id=staged_run.github_integration_id,
        github_installation_id=staged_run.github_installation_id,
        mcp_scope_preset=manifest["mcp_scope_preset"],
        disabled_tools=tuple(manifest["disabled_tools"]),
        phase=manifest["phase"],
    )


def _invalid_binding(message: str) -> NoReturn:
    raise InvalidStagedTaskBindingError(message)


def _manifest_payload(manifest: StagedCapabilityManifest) -> dict[str, object]:
    return {
        "version": manifest.version,
        "phase": manifest.phase,
        "mcp_scope_preset": manifest.mcp_scope_preset,
        "disabled_tools": list(manifest.disabled_tools),
    }


def _validate_manifest(manifest: StagedCapabilityManifest, *, expected_phase: str) -> None:
    if manifest.version != _MANIFEST_VERSION or manifest.phase != expected_phase:
        raise ValueError(f"Expected a version {_MANIFEST_VERSION} {expected_phase} manifest")
    if manifest.mcp_scope_preset not in get_args(McpScopePreset) or len(manifest.disabled_tools) != len(
        set(manifest.disabled_tools)
    ):
        raise ValueError("Staged capability manifest is invalid")


def _validate_idempotency_key(key: str) -> None:
    if not key or len(key) > 255:
        raise ValueError("Staged task idempotency key is invalid")


def _repository_fields(binding: StagedRepositoryBinding | None) -> dict[str, object]:
    if binding is None:
        return {
            "repository": None,
            "base_sha": None,
            "base_branch": None,
            "github_integration_id": None,
            "github_installation_id": None,
            "grant_version": None,
        }
    if not all(
        (
            binding.repository,
            binding.base_sha,
            binding.base_branch,
            binding.github_integration_id,
            binding.github_installation_id,
            binding.grant_version,
        )
    ):
        raise ValueError("Staged repository binding is incomplete")
    repository = binding.repository.strip()
    parts = repository.split("/")
    if len(parts) != 2 or not all(_REPOSITORY_SEGMENT.fullmatch(part) for part in parts):
        raise ValueError("Staged repository binding must be an owner/repository path")
    if not _COMMIT_SHA.fullmatch(binding.base_sha):
        raise ValueError("Staged repository binding must use an immutable commit SHA")
    return {
        "repository": repository.lower(),
        "base_sha": binding.base_sha.lower(),
        "base_branch": binding.base_branch,
        "github_integration_id": binding.github_integration_id,
        "github_installation_id": binding.github_installation_id,
        "grant_version": binding.grant_version,
    }


def validate_staged_repository_grant(
    *, team_id: int, repository: str, github_integration_id: int, github_installation_id: str
) -> None:
    """Fail closed unless the current team installation still authorizes this exact repository."""
    integration = Integration.objects.filter(
        id=github_integration_id,
        team_id=team_id,
        kind=Integration.IntegrationKind.GITHUB,
        errors="",
    ).first()
    if (
        integration is None
        or str(integration.config.get("installation_id")) != github_installation_id
        or integration.repository_cache_updated_at is None
        or not any(
            str(cached.get("full_name", "")).casefold() == repository.casefold()
            for cached in GitHubIntegration(integration).list_all_cached_repositories(allow_refresh=False)
        )
    ):
        _invalid_binding("Staged task repository integration is not currently authorized for this repository")


def _validate_create_input(input: CreateStagedTaskInput) -> dict[str, object]:
    _validate_idempotency_key(input.idempotency_key)
    _validate_manifest(input.analysis_manifest, expected_phase="analysis")
    if not input.title.strip() or not input.description.strip():
        raise ValueError("Staged task title and description are required")
    if input.origin_product not in Task.OriginProduct.values:
        raise ValueError("Staged task origin product is invalid")
    if input.output_schema is not None:
        schema_size = len(json.dumps(input.output_schema, separators=(",", ":")).encode())
        if schema_size > _MAX_OUTPUT_SCHEMA_BYTES:
            raise ValueError("Staged task output schema is too large")
    team = Team.objects.filter(id=input.team_id).first()
    actor = User.objects.filter(id=input.actor_id).first()
    if team is None or actor is None or not user_has_current_team_access(actor, team):
        _invalid_binding("Staged task team or actor does not exist")
    repository_fields = _repository_fields(input.repository)
    integration_id = repository_fields["github_integration_id"]
    if isinstance(integration_id, int):
        validate_staged_repository_grant(
            team_id=input.team_id,
            repository=cast(str, repository_fields["repository"]),
            github_integration_id=integration_id,
            github_installation_id=cast(str, repository_fields["github_installation_id"]),
        )
    return repository_fields


def _created(staged_run: TaskStagedRun) -> CreatedStagedTask:
    return CreatedStagedTask(
        staged_run_id=staged_run.id,
        task_id=staged_run.task_id,
        analysis_run_id=staged_run.analysis_run_id,
    )


def _advanced(staged_run: TaskStagedRun) -> AdvancedStagedTask:
    if staged_run.execution_run_id is None:
        raise RuntimeError("Staged task execution run is missing")
    return AdvancedStagedTask(
        staged_run_id=staged_run.id,
        task_id=staged_run.task_id,
        analysis_run_id=staged_run.analysis_run_id,
        execution_run_id=staged_run.execution_run_id,
    )


def _same_creation(
    staged_run: TaskStagedRun, input: CreateStagedTaskInput, repository_fields: dict[str, object]
) -> bool:
    task = staged_run.task
    return (
        staged_run.caller_id == input.caller_id
        and staged_run.create_idempotency_key == input.idempotency_key
        and staged_run.analysis_manifest == _manifest_payload(input.analysis_manifest)
        and all(getattr(staged_run, field) == value for field, value in repository_fields.items())
        and task.title == input.title
        and task.description == input.description
        and task.origin_product == input.origin_product
        and task.created_by_id == input.actor_id
        and task.json_schema == input.output_schema
    )


def create_staged_task_run(input: CreateStagedTaskInput) -> CreatedStagedTask:
    from products.tasks.backend.logic.services.workflow_dispatch import (  # noqa: PLC0415 - avoids facade/Temporal import cycle
        WorkflowDispatchOptions,
        enqueue_or_start_workflow,
    )

    repository_fields = _validate_create_input(input)
    try:
        with transaction.atomic():
            existing = (
                TaskStagedRun.objects.for_team(input.team_id)
                .select_for_update(of=("self",))
                .select_related("task", "analysis_run")
                .filter(caller_id=input.caller_id, create_idempotency_key=input.idempotency_key)
                .first()
            )
            if existing is not None:
                if not _same_creation(existing, input, repository_fields):
                    _invalid_binding("Staged task create replay does not match its original binding")
                return _created(existing)

            repository = cast(str | None, repository_fields["repository"])
            github_integration_id = cast(int | None, repository_fields["github_integration_id"])
            task = Task.objects.create(
                team_id=input.team_id,
                created_by_id=input.actor_id,
                title=input.title,
                description=input.description,
                origin_product=input.origin_product,
                json_schema=input.output_schema,
                repository=repository,
                repositories=[repository] if repository else [],
                github_integration_id=github_integration_id,
            )
            analysis_run = TaskRun.objects.create(
                task=task,
                team_id=input.team_id,
                status=TaskRun.Status.QUEUED,
                queued_at=timezone.now(),
            )
            staged_run = TaskStagedRun.objects.for_team(input.team_id).create(
                team_id=input.team_id,
                caller_id=input.caller_id,
                task=task,
                analysis_run=analysis_run,
                analysis_manifest=_manifest_payload(input.analysis_manifest),
                create_idempotency_key=input.idempotency_key,
                **repository_fields,
            )
            enqueue_or_start_workflow(
                analysis_run,
                options=WorkflowDispatchOptions(
                    user_id=input.actor_id,
                    create_pr=False,
                    posthog_mcp_scopes=cast(PosthogMcpScopes, input.analysis_manifest.mcp_scope_preset),
                    force_durable_dispatch=True,
                ),
            )
            return _created(staged_run)
    except IntegrityError:
        existing = (
            TaskStagedRun.objects.for_team(input.team_id)
            .select_related("task", "analysis_run")
            .filter(caller_id=input.caller_id, create_idempotency_key=input.idempotency_key)
            .first()
        )
        if existing is None or not _same_creation(existing, input, repository_fields):
            _invalid_binding("Staged task create replay does not match its original binding")
        return _created(existing)


def advance_staged_task_run(input: AdvanceStagedTaskInput) -> AdvancedStagedTask:
    from products.tasks.backend.facade.api import (
        get_resume_snapshot_carry_state,  # noqa: PLC0415 - facade initializes this service
    )
    from products.tasks.backend.logic.services.workflow_dispatch import (  # noqa: PLC0415 - avoids facade/Temporal import cycle
        WorkflowDispatchOptions,
        enqueue_or_start_workflow,
    )

    _validate_idempotency_key(input.idempotency_key)
    _validate_manifest(input.execution_manifest, expected_phase="execution")
    manifest_payload = _manifest_payload(input.execution_manifest)
    with transaction.atomic():
        try:
            staged_run = (
                TaskStagedRun.objects.for_team(input.team_id)
                .select_for_update(of=("self",))
                .select_related("task", "task__created_by", "task__team", "analysis_run", "execution_run")
                .get(id=input.staged_run_id, caller_id=input.caller_id)
            )
        except TaskStagedRun.DoesNotExist:
            _invalid_binding("Staged task is not bound to this team and caller")

        if staged_run.cancelled_at is not None or staged_run.capabilities_revoked_at is not None:
            _invalid_binding("Staged task capabilities are no longer active")
        if staged_run.task.created_by is None or not user_has_current_team_access(
            staged_run.task.created_by, staged_run.task.team
        ):
            _invalid_binding("Staged task actor no longer has team access")
        if staged_run.execution_run_id is not None:
            if (
                staged_run.advance_idempotency_key != input.idempotency_key
                or staged_run.execution_manifest != manifest_payload
            ):
                _invalid_binding("Staged task advance replay does not match its original binding")
            return _advanced(staged_run)
        snapshot_state = get_resume_snapshot_carry_state(staged_run.analysis_run.state)
        snapshot_ref = snapshot_state.get("snapshot_external_id")
        if staged_run.analysis_run.status != TaskRun.Status.COMPLETED or not isinstance(snapshot_ref, str):
            _invalid_binding("Staged task analysis has not produced a resumable workspace")
        snapshot_state["resume_from_run_id"] = str(staged_run.analysis_run_id)

        execution_run = TaskRun.objects.create(
            task=staged_run.task,
            team_id=staged_run.team_id,
            status=TaskRun.Status.QUEUED,
            queued_at=timezone.now(),
            state=snapshot_state,
        )
        staged_run.execution_run = execution_run
        staged_run.advance_idempotency_key = input.idempotency_key
        staged_run.execution_manifest = manifest_payload
        staged_run.workspace_snapshot_ref = snapshot_ref
        staged_run.save(
            update_fields=[
                "execution_run",
                "advance_idempotency_key",
                "execution_manifest",
                "workspace_snapshot_ref",
                "updated_at",
            ]
        )
        enqueue_or_start_workflow(
            execution_run,
            options=WorkflowDispatchOptions(
                user_id=staged_run.task.created_by_id,
                create_pr=False,
                posthog_mcp_scopes=cast(PosthogMcpScopes, input.execution_manifest.mcp_scope_preset),
                force_durable_dispatch=True,
            ),
        )
        return _advanced(staged_run)


def cancel_staged_task_run(*, team_id: int, caller_id: UUID, staged_run_id: UUID) -> bool:
    with transaction.atomic():
        try:
            staged_run = (
                TaskStagedRun.objects.for_team(team_id)
                .select_for_update(of=("self",))
                .get(id=staged_run_id, caller_id=caller_id)
            )
        except TaskStagedRun.DoesNotExist:
            return False
        if staged_run.cancelled_at is None:
            staged_run.cancelled_at = timezone.now()
            staged_run.save(update_fields=["cancelled_at", "updated_at"])
        return True
