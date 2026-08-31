"""Durable staged TaskRun creation and capability activation.

The API in this module is intentionally caller-neutral: callers identify themselves with
durable ids and pass frozen contracts, while Tasks owns all Task, TaskRun, transition,
and publication-lease writes.
"""

from __future__ import annotations

import re
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Literal, TypeVar
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone as django_timezone

from posthog.dataclasses import frozen
from posthog.models import Integration, Team
from posthog.models.github_integration_base import INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, GitHubIntegration

from products.tasks.backend.exceptions import TaskInvalidStateError
from products.tasks.backend.facade import contracts
from products.tasks.backend.logic.services.repository_authorization import repository_is_authorizable
from products.tasks.backend.models import (
    Task,
    TaskDraftPublication,
    TaskPublicationLease,
    TaskRun,
    TaskStagedRunTransition,
)

_MANIFEST_VERSION = 1
_ANALYSIS_CAPABILITIES = frozenset({"read", "research"})
_EXECUTION_CAPABILITIES = frozenset({"read", "research", "draft", "experiment_draft"})
_TERMINAL_SOURCE_STATUSES = frozenset({TaskRun.Status.CANCELLED, TaskRun.Status.FAILED})
MAX_STAGED_PUBLICATION_LEASE_LIFETIME = timedelta(hours=1)
MIN_STAGED_PUBLICATION_FINALIZATION_MARGIN = timedelta(seconds=1)
_PUBLICATION_COMMIT_AUTHOR_NAME = "PostHog Tasks"
_PUBLICATION_COMMIT_AUTHOR_EMAIL = "tasks@posthog.com"
_STAGED_REVOCATION_MARKERS = frozenset({"timed_out_inactivity", "timed_out_wall_clock", "sandbox_gone"})
_T = TypeVar("_T")
_BUNDLE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_BUNDLE_CONTENT_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE_BRANCH_REF_CHARS = frozenset("~^:?*[\\")
_GITHUB_APP_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,252}[a-z0-9])?$")
_STAGED_OUTPUT_SCHEMA_MAX_BYTES = 20_000
_STAGED_CONTEXT_WINDOWS = frozenset({"200k", "1m"})
StagedPublicationValidationMode = Literal[
    "start_mutation",
    "in_flight_mutation",
    "continue_external_mutation",
    "reconcile_after_expiry",
]
_EXTERNALLY_ATTEMPTED_PUBLICATION_STATUSES = frozenset(
    {
        TaskDraftPublication.Status.BRANCH_CREATING,
        TaskDraftPublication.Status.BRANCH_CREATED,
        TaskDraftPublication.Status.PR_CREATING,
        TaskDraftPublication.Status.PUBLISHED,
        TaskDraftPublication.Status.PUBLICATION_UNKNOWN,
    }
)


@frozen
class ValidatedStagedExecutionBinding:
    repository: str
    base_sha: str


@frozen
class DraftPublicationReservation:
    publication_id: str
    repository: str
    base_sha: str
    base_branch: str
    branch: str


@frozen
class _GitHubAppIdentity:
    slug: str
    login: str


def _invalid(code: str) -> ValueError:
    return ValueError(code)


def _staged_dispatch_intent(
    actor_id: int | None, mcp_scope_preset: Literal["read_only", "pulse_analysis"]
) -> dict[str, object]:
    """Build the durable dispatch payload used by both staged-run starts and recovery."""
    from products.tasks.backend.logic.services.workflow_dispatch import (  # noqa: PLC0415 — keeps Temporal imports off the facade startup path
        WorkflowDispatchOptions,
        build_create_payload,
    )

    return build_create_payload(
        WorkflowDispatchOptions(user_id=actor_id, create_pr=False, posthog_mcp_scopes=mcp_scope_preset)
    )


def _schedule_staged_run(run_id: str) -> None:
    """Delay the Temporal-coupled dispatcher import until after the durable write commits."""
    from products.tasks.backend.logic.services.workflow_dispatch import (  # noqa: PLC0415 — keeps Temporal imports off the facade startup path
        enqueue_or_start_workflow,
        parse_create_payload,
    )

    run = TaskRun.objects.select_related("task", "task__team", "task__created_by").get(id=run_id)
    state = run.state if isinstance(run.state, dict) else {}
    pending_dispatch = state.get("pending_dispatch")
    if not isinstance(pending_dispatch, dict):
        raise _invalid("staged_task_dispatch_intent_missing")
    enqueue_or_start_workflow(run, options=parse_create_payload(pending_dispatch))


def _manifest_payload(
    manifest: contracts.CapabilityManifestDTO,
    *,
    caller_id: str,
    task_id: str,
    run_id: str,
    publication_allowed: bool,
) -> dict[str, object]:
    return {
        "version": manifest.version,
        "phase": manifest.phase,
        "capabilities": list(manifest.capabilities),
        "bindings": {
            "caller_id": caller_id,
            "task_id": task_id,
            "run_id": run_id,
            "publication_allowed": publication_allowed,
        },
    }


def _validate_manifest(manifest: contracts.CapabilityManifestDTO, expected_phase: str) -> None:
    allowed_capabilities = _ANALYSIS_CAPABILITIES if expected_phase == "analysis" else _EXECUTION_CAPABILITIES
    if manifest.version != _MANIFEST_VERSION or manifest.phase != expected_phase:
        raise _invalid("staged_task_manifest_invalid")
    if not manifest.capabilities or not set(manifest.capabilities).issubset(allowed_capabilities):
        raise _invalid("staged_task_manifest_invalid")


def _validate_task_identity(task: Task, *, team_id: int, caller_id: str, idempotency_key: str) -> None:
    state = task.state if isinstance(task.state, dict) else {}
    if (
        task.team_id != team_id
        or state.get("staged_caller_id") != caller_id
        or state.get("staged_idempotency_key") != idempotency_key
    ):
        raise _invalid("staged_task_identity_mismatch")


def _validate_run_identity(run: TaskRun, task: Task, team_id: int) -> None:
    if run.team_id != team_id or run.task_id != task.id:
        raise _invalid("staged_task_identity_mismatch")


def _validate_transition_identity(
    transition: TaskStagedRunTransition,
    *,
    task: Task,
    source_run: TaskRun,
    team_id: int,
    caller_id: str,
) -> None:
    if (
        transition.team_id != team_id
        or str(transition.caller_id) != caller_id
        or transition.task_id != task.id
        or transition.source_task_run_id != source_run.id
    ):
        raise _invalid("staged_task_identity_mismatch")


def _validate_lease_identity(
    lease: TaskPublicationLease,
    *,
    transition: TaskStagedRunTransition,
    successor_run: TaskRun,
    team_id: int,
    caller_id: str,
) -> None:
    if (
        lease.team_id != team_id
        or str(lease.caller_id) != caller_id
        or lease.task_id != transition.task_id
        or lease.staged_run_transition_id != transition.id
        or lease.task_run_id != successor_run.id
    ):
        raise _invalid("staged_task_identity_mismatch")


def _validate_lease_bindings(
    lease: TaskPublicationLease, reservation: contracts.PublicationLeaseReservationDTO
) -> None:
    if (
        lease.logical_artifact_key != reservation.logical_artifact_key
        or lease.action_key != reservation.action_key
        or lease.repository != reservation.repository
        or lease.base_sha != reservation.base_sha
        or lease.base_branch != reservation.base_branch
        or lease.commit_message != reservation.commit_message
        or lease.pr_title != reservation.pr_title
        or lease.pr_body != reservation.pr_body
        or lease.github_integration_id != reservation.github_integration_id
        or lease.github_installation_id != reservation.github_installation_id
        or lease.grant_version != reservation.grant_version
        or lease.publication_mode != TaskPublicationLease.PublicationMode.DRAFT
    ):
        raise _invalid("publication_lease_binding_mismatch")


def _validate_repository_grant_input(
    repository: str | None,
    repository_grant: contracts.RepositoryGrantBindingDTO | None,
    *,
    team_id: int,
) -> Integration | None:
    if repository is None:
        if repository_grant is not None:
            raise _invalid("staged_repository_grant_unexpected")
        return None
    if repository_grant is None:
        raise _invalid("staged_repository_grant_required")
    if (
        not repository
        or repository_grant.repository != repository
        or not repository_grant.github_installation_id
        or not repository_grant.grant_version
    ):
        raise _invalid("staged_repository_grant_invalid")
    try:
        integration = (
            Integration.objects.select_for_update(of=("self",))
            .filter(
                id=repository_grant.github_integration_id,
                team_id=team_id,
                kind=Integration.IntegrationKind.GITHUB,
                integration_id=repository_grant.github_installation_id,
            )
            .exclude(errors=ERROR_TOKEN_REFRESH_FAILED)
            .exclude(config__has_key=INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY)
            .get()
        )
    except Integration.DoesNotExist as error:
        raise _invalid("staged_repository_grant_inactive") from error
    if not repository_is_authorizable(integration.repository_cache, repository):
        raise _invalid("staged_repository_grant_inactive")
    return integration


def resolve_staged_repository_base(
    input: contracts.ResolveStagedRepositoryBaseInput,
) -> contracts.RepositoryBaseBindingDTO:
    """Resolve and revalidate the exact default-branch head through the Tasks-owned GitHub transport."""
    with transaction.atomic():
        Team.objects.select_for_update(of=("self",)).get(id=input.team_id)
        integration = _validate_repository_grant_input(
            input.repository_grant.repository,
            input.repository_grant,
            team_id=input.team_id,
        )
        assert integration is not None

    github = GitHubIntegration(integration, source="tasks_staged_analysis")
    repository = input.repository_grant.repository
    try:
        owner, repository_name = repository.split("/", 1)
        if owner.casefold() != github.organization().casefold():
            raise _invalid("staged_repository_grant_invalid")
        base_branch = github.get_default_branch(repository)
        branch_info = github.get_branch_info(repository_name, base_branch)
    except Exception as error:  # noqa: BLE001 — normalize GitHub transport failures to a stable facade error
        raise _invalid("staged_repository_base_unavailable") from error
    base_sha = branch_info.get("commit_sha") if branch_info.get("success") is True else None
    if (
        branch_info.get("exists") is not True
        or not isinstance(base_sha, str)
        or not _BUNDLE_SHA_RE.fullmatch(base_sha)
        or not _is_safe_branch_ref(base_branch)
    ):
        raise _invalid("staged_repository_base_unavailable")

    with transaction.atomic():
        Team.objects.select_for_update(of=("self",)).get(id=input.team_id)
        _validate_repository_grant_input(repository, input.repository_grant, team_id=input.team_id)
    return contracts.RepositoryBaseBindingDTO(
        repository=repository,
        base_sha=base_sha,
        base_branch=base_branch,
    )


def _validate_repository_base_input(
    repository: str | None,
    repository_base: contracts.RepositoryBaseBindingDTO | None,
) -> None:
    if repository is None:
        if repository_base is not None:
            raise _invalid("staged_repository_base_unexpected")
        return
    if (
        repository_base is None
        or repository_base.repository != repository
        or not _BUNDLE_SHA_RE.fullmatch(repository_base.base_sha)
        or not _is_safe_branch_ref(repository_base.base_branch)
    ):
        raise _invalid("staged_repository_base_invalid")


def _validate_output_schema(output_schema: dict | None) -> None:
    if output_schema is None:
        return
    try:
        encoded = json.dumps(output_schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise _invalid("staged_task_output_schema_invalid") from error
    if output_schema.get("type") != "object" or len(encoded) > _STAGED_OUTPUT_SCHEMA_MAX_BYTES:
        raise _invalid("staged_task_output_schema_invalid")


def _validate_context_window(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in _STAGED_CONTEXT_WINDOWS:
        raise _invalid("staged_task_context_window_invalid")
    return value


def _is_safe_branch_ref(value: str) -> bool:
    return (
        bool(value)
        and value != "@"
        and not value.startswith(("/", "."))
        and not value.endswith(("/", "."))
        and "@{" not in value
        and ".." not in value
        and "//" not in value
        and not any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
        and not any(character in _UNSAFE_BRANCH_REF_CHARS for character in value)
        and all(not component.endswith(".lock") for component in value.split("/"))
    )


def _validate_publication_metadata(reservation: contracts.PublicationLeaseReservationDTO) -> None:
    for value, maximum, required in (
        (reservation.commit_message, 500, True),
        (reservation.pr_title, 256, True),
        (reservation.pr_body, 20_000, False),
    ):
        if (
            not isinstance(value, str)
            or (required and not value)
            or "\x00" in value
            or len(value.encode("utf-8")) > maximum
        ):
            raise _invalid("staged_task_publication_metadata_invalid")


def _expected_github_app_identity() -> _GitHubAppIdentity:
    slug = getattr(settings, "GITHUB_APP_SLUG", "")
    if not isinstance(slug, str) or not _GITHUB_APP_SLUG_RE.fullmatch(slug):
        raise _invalid("staged_task_github_app_identity_missing")
    return _GitHubAppIdentity(slug=slug, login=f"{slug}[bot]")


def _task_repository_grant(task: Task) -> contracts.RepositoryGrantBindingDTO | None:
    state = task.state if isinstance(task.state, dict) else {}
    stored = state.get("staged_repository_grant")
    if task.repository is None:
        if task.github_integration_id is not None or stored is not None:
            raise _invalid("staged_repository_grant_mismatch")
        return None
    if (
        not isinstance(stored, dict)
        or stored.get("repository") != task.repository
        or type(stored.get("github_integration_id")) is not int
        or not isinstance(stored.get("github_installation_id"), str)
        or not isinstance(stored.get("grant_version"), str)
        or not stored["github_installation_id"]
        or not stored["grant_version"]
        or task.github_integration_id != stored["github_integration_id"]
    ):
        raise _invalid("staged_repository_grant_mismatch")
    return contracts.RepositoryGrantBindingDTO(
        repository=stored["repository"],
        github_integration_id=stored["github_integration_id"],
        github_installation_id=stored["github_installation_id"],
        grant_version=stored["grant_version"],
    )


def _task_repository_base(task: Task) -> contracts.RepositoryBaseBindingDTO | None:
    state = task.state if isinstance(task.state, dict) else {}
    stored = state.get("staged_repository_base")
    if task.repository is None:
        if stored is not None:
            raise _invalid("staged_repository_base_mismatch")
        return None
    if (
        not isinstance(stored, dict)
        or stored.get("repository") != task.repository
        or not isinstance(stored.get("base_sha"), str)
        or not isinstance(stored.get("base_branch"), str)
    ):
        raise _invalid("staged_repository_base_mismatch")
    base = contracts.RepositoryBaseBindingDTO(
        repository=stored["repository"],
        base_sha=stored["base_sha"],
        base_branch=stored["base_branch"],
    )
    _validate_repository_base_input(task.repository, base)
    return base


def _validate_task_repository_base(
    task: Task, expected: contracts.RepositoryBaseBindingDTO | None
) -> contracts.RepositoryBaseBindingDTO | None:
    actual = _task_repository_base(task)
    if actual != expected:
        raise _invalid("staged_repository_base_mismatch")
    return actual


def _validate_task_repository_grant(
    task: Task, expected: contracts.RepositoryGrantBindingDTO | None
) -> contracts.RepositoryGrantBindingDTO | None:
    actual = _task_repository_grant(task)
    if actual != expected:
        raise _invalid("staged_repository_grant_mismatch")
    return actual


def _staged_execution_invalid(run_id: str, reason: str) -> TaskInvalidStateError:
    return TaskInvalidStateError(
        f"Staged execution state is invalid: {reason}",
        {"run_id": run_id},
        cause=RuntimeError(reason),
    )


def _validate_staged_execution_manifest(
    manifest: object, *, task: Task, successor_run: TaskRun, caller_id: str
) -> bool:
    if not isinstance(manifest, dict):
        return False
    bindings = manifest.get("bindings")
    return (
        manifest.get("version") == _MANIFEST_VERSION
        and manifest.get("phase") == "execution"
        and isinstance(manifest.get("capabilities"), list)
        and bool(manifest["capabilities"])
        and set(manifest["capabilities"]).issubset(_EXECUTION_CAPABILITIES)
        and isinstance(bindings, dict)
        and bindings.get("caller_id") == caller_id
        and bindings.get("task_id") == str(task.id)
        and bindings.get("run_id") == str(successor_run.id)
        and isinstance(bindings.get("publication_allowed"), bool)
        and (bindings["publication_allowed"] is True or "experiment_draft" in manifest["capabilities"])
    )


def _validate_staged_analysis_manifest(manifest: object, *, task: Task, run: TaskRun, caller_id: str) -> bool:
    if not isinstance(manifest, dict):
        return False
    bindings = manifest.get("bindings")
    return (
        manifest.get("version") == _MANIFEST_VERSION
        and manifest.get("phase") == "analysis"
        and isinstance(manifest.get("capabilities"), list)
        and bool(manifest["capabilities"])
        and set(manifest["capabilities"]).issubset(_ANALYSIS_CAPABILITIES)
        and isinstance(bindings, dict)
        and bindings.get("caller_id") == caller_id
        and bindings.get("task_id") == str(task.id)
        and bindings.get("run_id") == str(run.id)
        and bindings.get("publication_allowed") is False
    )


def _validate_staged_analysis_for_provisioning(
    run_id: str, sandbox_backend: str
) -> ValidatedStagedExecutionBinding | None:
    unguarded_run = TaskRun.objects.only("id", "team_id", "task_id", "state").get(id=run_id)
    unguarded_state = unguarded_run.state if isinstance(unguarded_run.state, dict) else {}
    if unguarded_state.get("staged_phase") != "analysis":
        return None
    if sandbox_backend == "hogland":
        raise _staged_execution_invalid(run_id, "workspace_snapshot_unsupported")
    with transaction.atomic():
        Team.objects.select_for_update(of=("self",)).get(id=unguarded_run.team_id)
        task = Task.objects.select_for_update(of=("self",)).get(id=unguarded_run.task_id)
        run = TaskRun.objects.select_for_update(of=("self",)).get(id=unguarded_run.id)
        _validate_run_identity(run, task, unguarded_run.team_id)
        state = run.state if isinstance(run.state, dict) else {}
        task_state = task.state if isinstance(task.state, dict) else {}
        caller_id = task_state.get("staged_caller_id")
        if not isinstance(caller_id, str):
            raise _staged_execution_invalid(run_id, "staged_task_caller_missing")
        _validate_task_identity(
            task,
            team_id=unguarded_run.team_id,
            caller_id=caller_id,
            idempotency_key=task.origin_key or "",
        )
        if not _validate_staged_analysis_manifest(
            state.get("staged_manifest"), task=task, run=run, caller_id=caller_id
        ):
            raise _staged_execution_invalid(run_id, "staged_manifest_invalid")
        try:
            grant = _task_repository_grant(task)
            base = _task_repository_base(task)
        except ValueError as error:
            raise _staged_execution_invalid(run_id, "staged_repository_binding_mismatch") from error
        if task.repository is None:
            if (
                grant is not None
                or base is not None
                or state.get("credential_free_checkout") is not False
                or state.get("staged_repository") is not None
                or state.get("staged_base_sha") is not None
                or state.get("staged_base_branch") is not None
            ):
                raise _staged_execution_invalid(run_id, "staged_repository_binding_mismatch")
            return None
        if grant is None or base is None or task.github_integration_id != grant.github_integration_id:
            raise _staged_execution_invalid(run_id, "staged_repository_binding_mismatch")
        try:
            Integration.objects.select_for_update(of=("self",)).filter(
                id=grant.github_integration_id,
                team_id=unguarded_run.team_id,
                kind=Integration.IntegrationKind.GITHUB,
                integration_id=grant.github_installation_id,
            ).exclude(errors=ERROR_TOKEN_REFRESH_FAILED).exclude(
                config__has_key=INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY
            ).get()
        except Integration.DoesNotExist as error:
            raise _staged_execution_invalid(run_id, "staged_repository_grant_inactive") from error
        if (
            state.get("staged_repository") != base.repository
            or state.get("staged_base_sha") != base.base_sha
            or state.get("staged_base_branch") != base.base_branch
            or state.get("credential_free_checkout") is not True
        ):
            raise _staged_execution_invalid(run_id, "staged_repository_binding_mismatch")
        return ValidatedStagedExecutionBinding(repository=base.repository, base_sha=base.base_sha)


def _validate_staged_unleased_execution_for_provisioning(
    run_id: str, sandbox_backend: str
) -> ValidatedStagedExecutionBinding | None:
    unguarded_run = TaskRun.objects.only("id", "team_id", "task_id", "state").get(id=run_id)
    unguarded_state = unguarded_run.state if isinstance(unguarded_run.state, dict) else {}
    manifest = unguarded_state.get("staged_manifest")
    capabilities = manifest.get("capabilities") if isinstance(manifest, dict) else None
    if unguarded_state.get("staged_phase") != "execution" or not isinstance(capabilities, list):
        return None
    if isinstance(unguarded_state.get("publication_lease_id"), str):
        return None
    if "experiment_draft" not in capabilities:
        raise _staged_execution_invalid(run_id, "staged_manifest_invalid")
    if sandbox_backend == "hogland":
        raise _staged_execution_invalid(run_id, "workspace_snapshot_unsupported")
    transition_id = unguarded_state.get("staged_transition_id")
    if not isinstance(transition_id, str):
        raise _staged_execution_invalid(run_id, "staged_transition_missing")
    with transaction.atomic():
        Team.objects.select_for_update(of=("self",)).get(id=unguarded_run.team_id)
        task = Task.objects.select_for_update(of=("self",)).get(id=unguarded_run.task_id)
        run = TaskRun.objects.select_for_update(of=("self",)).get(id=unguarded_run.id)
        transition = (
            TaskStagedRunTransition.objects.for_team(unguarded_run.team_id)
            .select_for_update(of=("self",))
            .get(id=transition_id)
        )
        source_run = TaskRun.objects.select_for_update(of=("self",)).get(id=transition.source_task_run_id)
        state = run.state if isinstance(run.state, dict) else {}
        task_state = task.state if isinstance(task.state, dict) else {}
        caller_id = task_state.get("staged_caller_id")
        if not isinstance(caller_id, str):
            raise _staged_execution_invalid(run_id, "staged_task_caller_missing")
        _validate_task_identity(
            task,
            team_id=unguarded_run.team_id,
            caller_id=caller_id,
            idempotency_key=task.origin_key or "",
        )
        _validate_run_identity(source_run, task, unguarded_run.team_id)
        _validate_run_identity(run, task, unguarded_run.team_id)
        _validate_transition_identity(
            transition,
            task=task,
            source_run=source_run,
            team_id=unguarded_run.team_id,
            caller_id=caller_id,
        )
        source_state = source_run.state if isinstance(source_run.state, dict) else {}
        snapshot_ref = state.get("snapshot_external_id")
        if (
            transition.successor_task_run_id != run.id
            or transition.status != TaskStagedRunTransition.Status.ADVANCED
            or state.get("publication_lease_id") is not None
            or not isinstance(snapshot_ref, str)
            or state.get("resume_from_run_id") != str(source_run.id)
            or source_state.get("snapshot_external_id") != snapshot_ref
            or transition.source_workspace_snapshot_ref != snapshot_ref
            or not _validate_staged_execution_manifest(manifest, task=task, successor_run=run, caller_id=caller_id)
            or manifest != transition.requested_capability_manifest
            or state.get("staged_capabilities_revoked") is True
        ):
            raise _staged_execution_invalid(run_id, "staged_execution_binding_invalid")
        try:
            grant = _task_repository_grant(task)
            base = _task_repository_base(task)
        except ValueError as error:
            raise _staged_execution_invalid(run_id, "staged_repository_binding_mismatch") from error
        if task.repository is None:
            if (
                grant is not None
                or base is not None
                or state.get("credential_free_checkout") is not False
                or state.get("staged_repository") is not None
                or state.get("staged_base_sha") is not None
                or state.get("staged_base_branch") is not None
            ):
                raise _staged_execution_invalid(run_id, "staged_repository_binding_mismatch")
            return None
        if grant is None or base is None or task.github_integration_id != grant.github_integration_id:
            raise _staged_execution_invalid(run_id, "staged_repository_binding_mismatch")
        try:
            Integration.objects.select_for_update(of=("self",)).filter(
                id=grant.github_integration_id,
                team_id=unguarded_run.team_id,
                kind=Integration.IntegrationKind.GITHUB,
                integration_id=grant.github_installation_id,
            ).exclude(errors=ERROR_TOKEN_REFRESH_FAILED).exclude(
                config__has_key=INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY
            ).get()
        except Integration.DoesNotExist as error:
            raise _staged_execution_invalid(run_id, "staged_repository_grant_inactive") from error
        return ValidatedStagedExecutionBinding(repository=base.repository, base_sha=base.base_sha)


def _with_validated_staged_execution(
    run_id: str,
    sandbox_backend: str,
    operation: Callable[[Integration, Task, TaskRun, TaskStagedRunTransition, TaskRun, TaskPublicationLease], _T],
    *,
    allow_expired_lease: bool = False,
    allow_revoked_capabilities: bool = False,
    allow_finalized_lease: bool = False,
) -> _T | None:
    """Run a caller-neutral operation under the staged execution's global lock order."""
    unguarded_successor = TaskRun.objects.only("id", "team_id", "task_id", "state").get(id=run_id)
    unguarded_state = unguarded_successor.state if isinstance(unguarded_successor.state, dict) else {}
    if unguarded_state.get("staged_phase") != "execution":
        return None
    transition_id = unguarded_state.get("staged_transition_id")
    if not isinstance(transition_id, str):
        raise _staged_execution_invalid(run_id, "staged_transition_missing")
    try:
        unguarded_transition = (
            TaskStagedRunTransition.objects.unscoped().only("source_task_run_id").get(id=transition_id)
        )
    except TaskStagedRunTransition.DoesNotExist as error:
        raise _staged_execution_invalid(run_id, "staged_transition_missing") from error
    lease_expired = False
    try:
        unguarded_task = Task.objects.only("id", "team_id", "github_integration_id").get(id=unguarded_successor.task_id)
    except Task.DoesNotExist as error:
        raise _staged_execution_invalid(run_id, "staged_task_missing") from error
    if unguarded_task.team_id != unguarded_successor.team_id:
        raise _staged_execution_invalid(run_id, "staged_task_identity_mismatch")
    if unguarded_task.github_integration_id is None:
        raise _staged_execution_invalid(run_id, "staged_repository_grant_missing")
    with transaction.atomic():
        Team.objects.select_for_update(of=("self",)).get(id=unguarded_successor.team_id)
        try:
            github_integration = (
                Integration.objects.select_for_update(of=("self",))
                .filter(
                    id=unguarded_task.github_integration_id,
                    team_id=unguarded_successor.team_id,
                    kind=Integration.IntegrationKind.GITHUB,
                )
                .exclude(errors=ERROR_TOKEN_REFRESH_FAILED)
                .exclude(config__has_key=INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY)
                .get()
            )
        except Integration.DoesNotExist as error:
            raise _staged_execution_invalid(run_id, "staged_repository_grant_inactive") from error
        task = Task.objects.select_for_update(of=("self",)).get(id=unguarded_successor.task_id)
        if task.github_integration_id != github_integration.id:
            raise _staged_execution_invalid(run_id, "staged_repository_grant_mismatch")
        try:
            source_run = TaskRun.objects.select_for_update(of=("self",)).get(id=unguarded_transition.source_task_run_id)
        except TaskRun.DoesNotExist as error:
            raise _staged_execution_invalid(run_id, "staged_source_missing") from error
        try:
            transition = (
                TaskStagedRunTransition.objects.unscoped().select_for_update(of=("self",)).get(id=transition_id)
            )
        except TaskStagedRunTransition.DoesNotExist as error:
            raise _staged_execution_invalid(run_id, "staged_transition_missing") from error
        successor_run = TaskRun.objects.select_for_update(of=("self",)).get(id=run_id)
        state = successor_run.state if isinstance(successor_run.state, dict) else {}
        if state.get("staged_phase") != "execution" or state.get("staged_transition_id") != transition_id:
            raise _staged_execution_invalid(run_id, "staged_transition_changed")
        task_state = task.state if isinstance(task.state, dict) else {}
        caller_id = task_state.get("staged_caller_id")
        if not isinstance(caller_id, str):
            raise _staged_execution_invalid(run_id, "staged_task_caller_missing")
        _validate_task_identity(
            task,
            team_id=successor_run.team_id,
            caller_id=caller_id,
            idempotency_key=task.origin_key or "",
        )
        _validate_run_identity(source_run, task, successor_run.team_id)
        _validate_run_identity(successor_run, task, successor_run.team_id)
        try:
            _validate_transition_identity(
                transition,
                task=task,
                source_run=source_run,
                team_id=successor_run.team_id,
                caller_id=caller_id,
            )
        except ValueError as error:
            raise _staged_execution_invalid(run_id, "staged_transition_identity_mismatch") from error
        if (
            transition.successor_task_run_id != successor_run.id
            or transition.status != TaskStagedRunTransition.Status.ADVANCED
        ):
            raise _staged_execution_invalid(run_id, "staged_transition_successor_invalid")
        source_state = source_run.state if isinstance(source_run.state, dict) else {}
        snapshot_ref = state.get("snapshot_external_id")
        if (
            not isinstance(snapshot_ref, str)
            or state.get("resume_from_run_id") != str(source_run.id)
            or source_state.get("snapshot_external_id") != snapshot_ref
            or transition.source_workspace_snapshot_ref != snapshot_ref
        ):
            raise _staged_execution_invalid(run_id, "staged_snapshot_mismatch")
        manifest = state.get("staged_manifest")
        if not _validate_staged_execution_manifest(
            manifest, task=task, successor_run=successor_run, caller_id=caller_id
        ):
            raise _staged_execution_invalid(run_id, "staged_manifest_invalid")
        if manifest != transition.requested_capability_manifest:
            raise _staged_execution_invalid(run_id, "staged_manifest_mismatch")
        lease_id = state.get("publication_lease_id")
        if not isinstance(lease_id, str):
            raise _staged_execution_invalid(run_id, "staged_lease_missing")
        try:
            lease = TaskPublicationLease.objects.unscoped().select_for_update(of=("self",)).get(id=lease_id)
        except TaskPublicationLease.DoesNotExist as error:
            raise _staged_execution_invalid(run_id, "staged_lease_missing") from error
        try:
            _validate_lease_identity(
                lease,
                transition=transition,
                successor_run=successor_run,
                team_id=successor_run.team_id,
                caller_id=caller_id,
            )
        except ValueError as error:
            raise _staged_execution_invalid(run_id, "staged_lease_identity_mismatch") from error
        try:
            task_grant = _task_repository_grant(task)
        except ValueError as error:
            raise _staged_execution_invalid(run_id, "staged_repository_binding_mismatch") from error
        if (
            task.repository != lease.repository
            or task_grant is None
            or task_grant.github_integration_id != lease.github_integration_id
            or task_grant.github_installation_id != lease.github_installation_id
            or task_grant.grant_version != lease.grant_version
            or str(github_integration.integration_id) != task_grant.github_installation_id
            or not _is_safe_branch_ref(lease.base_branch or "")
            or lease.head_branch != f"codex/{lease.id.hex}"
            or lease.starts_before is None
        ):
            raise _staged_execution_invalid(run_id, "staged_repository_binding_mismatch")
        current_time = django_timezone.now()
        if (
            lease.status == TaskPublicationLease.Status.ACTIVE
            and lease.expires_at <= current_time
            and not allow_expired_lease
        ):
            expired = (
                TaskPublicationLease.objects.for_team(successor_run.team_id)
                .filter(id=lease.id, status=TaskPublicationLease.Status.ACTIVE, expires_at__lte=current_time)
                .update(status=TaskPublicationLease.Status.EXPIRED, expired_at=current_time)
            )
            lease_expired = bool(expired)
        if (
            not lease_expired
            and lease.status != TaskPublicationLease.Status.ACTIVE
            and not (allow_finalized_lease and lease.status == TaskPublicationLease.Status.FINALIZED)
        ):
            raise _staged_execution_invalid(run_id, "publication_lease_inactive")
        if not lease_expired and state.get("staged_capabilities_revoked") is True and not allow_revoked_capabilities:
            raise _staged_execution_invalid(run_id, "staged_capabilities_revoked")
        if not lease_expired and sandbox_backend == "hogland":
            raise TaskInvalidStateError(
                "workspace_snapshot_unsupported",
                {"task_id": str(task.id), "run_id": run_id},
                cause=RuntimeError("workspace_snapshot_unsupported"),
            )
        if not lease_expired:
            return operation(github_integration, task, source_run, transition, successor_run, lease)
    if lease_expired:
        raise _staged_execution_invalid(run_id, "publication_lease_expired")
    raise AssertionError("staged execution operation completed without a result")


def validate_staged_execution_for_provisioning(
    run_id: str, sandbox_backend: str
) -> ValidatedStagedExecutionBinding | None:
    """Lock and verify a durable staged analysis or execution before sandbox provisioning."""
    analysis_binding = _validate_staged_analysis_for_provisioning(run_id, sandbox_backend)
    if analysis_binding is not None:
        return analysis_binding
    run_state = TaskRun.objects.only("state").get(id=run_id).state
    state = run_state if isinstance(run_state, dict) else {}
    manifest = state.get("staged_manifest")
    capabilities = manifest.get("capabilities") if isinstance(manifest, dict) else None
    unleased_execution_binding = _validate_staged_unleased_execution_for_provisioning(run_id, sandbox_backend)
    if unleased_execution_binding is not None or (
        state.get("staged_phase") == "execution"
        and state.get("publication_lease_id") is None
        and isinstance(capabilities, list)
        and "experiment_draft" in capabilities
    ):
        return unleased_execution_binding
    return _with_validated_staged_execution(
        run_id,
        sandbox_backend,
        lambda _integration, _task, _source_run, _transition, _successor_run, lease: ValidatedStagedExecutionBinding(
            repository=lease.repository,
            base_sha=lease.base_sha,
        ),
    )


def reserve_staged_draft_publication(run_id: str) -> DraftPublicationReservation:
    """Reserve the single server-owned draft publication for a validated execution run."""

    def _reserve(
        _integration: Integration,
        task: Task,
        _source_run: TaskRun,
        _transition: TaskStagedRunTransition,
        _successor_run: TaskRun,
        lease: TaskPublicationLease,
    ) -> DraftPublicationReservation:
        if lease.starts_before is None or lease.starts_before <= django_timezone.now():
            raise _staged_execution_invalid(run_id, "publication_lease_start_cutoff")
        publication, _created = TaskDraftPublication.objects.for_team(task.team_id).get_or_create(
            lease=lease,
            defaults={
                "team_id": task.team_id,
                "repository": lease.repository,
                "base_sha": lease.base_sha,
                "base_branch": lease.base_branch,
                "commit_message": lease.commit_message,
                "pr_title": lease.pr_title,
                "pr_body": lease.pr_body,
                "commit_author_name": lease.commit_author_name,
                "commit_author_email": lease.commit_author_email,
                "commit_timestamp": lease.commit_timestamp,
                "branch": f"codex/{lease.id.hex}",
                "expected_github_app_slug": lease.expected_github_app_slug,
                "expected_github_app_login": lease.expected_github_app_login,
            },
        )
        if (
            publication.repository != lease.repository
            or publication.base_sha != lease.base_sha
            or publication.base_branch != lease.base_branch
            or publication.commit_message != lease.commit_message
            or publication.pr_title != lease.pr_title
            or publication.pr_body != lease.pr_body
            or publication.commit_author_name != lease.commit_author_name
            or publication.commit_author_email != lease.commit_author_email
            or publication.commit_timestamp != lease.commit_timestamp
            or publication.expected_github_app_slug != lease.expected_github_app_slug
            or publication.expected_github_app_login != lease.expected_github_app_login
            or publication.branch != f"codex/{lease.id.hex}"
            or not publication.is_draft
        ):
            raise _staged_execution_invalid(run_id, "draft_publication_binding_mismatch")
        return DraftPublicationReservation(
            publication_id=str(publication.id),
            repository=publication.repository,
            base_sha=publication.base_sha,
            base_branch=publication.base_branch,
            branch=publication.branch,
        )

    reservation = _with_validated_staged_execution(run_id, "modal", _reserve)
    if reservation is None:
        raise _staged_execution_invalid(run_id, "staged_execution_required")
    return reservation


def record_staged_draft_publication_bundle(
    run_id: str,
    *,
    storage_path: str,
    bundle_head_sha: str,
    bundle_sha256: str,
    bundle_byte_count: int,
) -> None:
    """Attach one trusted bundle reference to the locked server-owned publication claim."""
    if (
        not _BUNDLE_SHA_RE.fullmatch(bundle_head_sha)
        or not _BUNDLE_CONTENT_SHA_RE.fullmatch(bundle_sha256)
        or bundle_byte_count <= 0
    ):
        raise _staged_execution_invalid(run_id, "draft_bundle_invalid")

    def _record(
        _integration: Integration,
        _task: Task,
        _source_run: TaskRun,
        _transition: TaskStagedRunTransition,
        _successor_run: TaskRun,
        lease: TaskPublicationLease,
        publication: TaskDraftPublication,
    ) -> bool:
        if storage_path != f"tasks/draft-publications/{publication.id}/{bundle_sha256}.bundle":
            raise _staged_execution_invalid(run_id, "draft_bundle_invalid")
        if publication.status == TaskDraftPublication.Status.UPLOADED:
            if (
                publication.bundle_storage_path == storage_path
                and publication.bundle_head_sha == bundle_head_sha
                and publication.bundle_sha256 == bundle_sha256
                and publication.bundle_byte_count == bundle_byte_count
            ):
                return True
            raise _staged_execution_invalid(run_id, "draft_bundle_conflict")
        if publication.status != TaskDraftPublication.Status.RESERVED:
            raise _staged_execution_invalid(run_id, "draft_publication_inactive")
        publication.status = TaskDraftPublication.Status.UPLOADED
        publication.bundle_storage_path = storage_path
        publication.bundle_head_sha = bundle_head_sha
        publication.bundle_sha256 = bundle_sha256
        publication.bundle_byte_count = bundle_byte_count
        publication.uploaded_at = django_timezone.now()
        publication.save(
            update_fields=[
                "status",
                "bundle_storage_path",
                "bundle_head_sha",
                "bundle_sha256",
                "bundle_byte_count",
                "uploaded_at",
                "updated_at",
            ]
        )
        return True

    result = with_validated_staged_draft_publication(run_id, _record, mode="start_mutation")
    if result is not True:
        raise _staged_execution_invalid(run_id, "staged_execution_required")


def with_validated_staged_draft_publication(
    run_id: str,
    operation: Callable[
        [Integration, Task, TaskRun, TaskStagedRunTransition, TaskRun, TaskPublicationLease, TaskDraftPublication], _T
    ],
    *,
    mode: StagedPublicationValidationMode = "in_flight_mutation",
) -> _T:
    """Run one server-side publication state transition under the global staged lock order."""

    def _operate(
        integration: Integration,
        task: Task,
        source_run: TaskRun,
        transition: TaskStagedRunTransition,
        successor_run: TaskRun,
        lease: TaskPublicationLease,
    ) -> tuple[_T]:
        try:
            publication = (
                TaskDraftPublication.objects.for_team(task.team_id)
                .select_for_update(of=("self",))
                .get(lease_id=lease.id)
            )
        except TaskDraftPublication.DoesNotExist as error:
            raise _staged_execution_invalid(run_id, "draft_publication_missing") from error
        if (
            publication.team_id != task.team_id
            or publication.lease_id != lease.id
            or publication.repository != lease.repository
            or publication.base_sha != lease.base_sha
            or publication.base_branch != lease.base_branch
            or publication.commit_message != lease.commit_message
            or publication.pr_title != lease.pr_title
            or publication.pr_body != lease.pr_body
            or publication.commit_author_name != lease.commit_author_name
            or publication.commit_author_email != lease.commit_author_email
            or publication.commit_timestamp != lease.commit_timestamp
            or publication.expected_github_app_slug != lease.expected_github_app_slug
            or publication.expected_github_app_login != lease.expected_github_app_login
            or publication.branch != f"codex/{lease.id.hex}"
            or not publication.is_draft
        ):
            raise _staged_execution_invalid(run_id, "draft_publication_binding_mismatch")
        if mode == "start_mutation" and (lease.starts_before is None or lease.starts_before <= django_timezone.now()):
            raise _staged_execution_invalid(run_id, "publication_lease_start_cutoff")
        if mode == "continue_external_mutation":
            successor_state = successor_run.state if isinstance(successor_run.state, dict) else {}
            if (
                lease.status != TaskPublicationLease.Status.ACTIVE
                or lease.expires_at <= django_timezone.now()
                or successor_state.get("staged_capabilities_revoked") is True
                or publication.status != TaskDraftPublication.Status.BRANCH_CREATED
            ):
                raise _staged_execution_invalid(run_id, "draft_publication_external_mutation_unavailable")
        if mode == "reconcile_after_expiry":
            if lease.status == TaskPublicationLease.Status.FINALIZED:
                if publication.status != TaskDraftPublication.Status.FINALIZED:
                    raise _staged_execution_invalid(run_id, "draft_publication_reconciliation_unavailable")
            elif (
                lease.status != TaskPublicationLease.Status.ACTIVE
                or publication.status not in _EXTERNALLY_ATTEMPTED_PUBLICATION_STATUSES
            ):
                raise _staged_execution_invalid(run_id, "draft_publication_reconciliation_unavailable")
        return (operation(integration, task, source_run, transition, successor_run, lease, publication),)

    result = _with_validated_staged_execution(
        run_id,
        "modal",
        _operate,
        allow_expired_lease=mode in {"continue_external_mutation", "reconcile_after_expiry"},
        allow_revoked_capabilities=mode in {"continue_external_mutation", "reconcile_after_expiry"},
        allow_finalized_lease=mode == "reconcile_after_expiry",
    )
    if result is None:
        raise _staged_execution_invalid(run_id, "staged_execution_required")
    return result[0]


def create_staged_task(input: contracts.CreateStagedTaskInput) -> contracts.CreatedStagedTaskDTO:
    """Create one analysis TaskRun and schedule it after its transaction commits."""
    _validate_manifest(input.analysis_manifest, "analysis")
    _validate_repository_base_input(input.repository, input.repository_base)
    _validate_output_schema(input.output_schema)
    context_window = _validate_context_window(input.context_window)
    if input.mcp_scope_preset not in {"read_only", "pulse_analysis"}:
        raise _invalid("staged_task_mcp_scope_invalid")
    caller_id = str(input.caller_id)
    with transaction.atomic():
        Team.objects.select_for_update(of=("self",)).get(id=input.team_id)
        github_integration = _validate_repository_grant_input(
            input.repository,
            input.repository_grant,
            team_id=input.team_id,
        )
        existing = (
            Task.objects.select_for_update(of=("self",))
            .filter(team_id=input.team_id, origin_key=input.idempotency_key)
            .first()
        )
        if existing is not None:
            _validate_task_identity(
                existing, team_id=input.team_id, caller_id=caller_id, idempotency_key=input.idempotency_key
            )
            _validate_task_repository_grant(existing, input.repository_grant)
            _validate_task_repository_base(existing, input.repository_base)
            existing_state = existing.state if isinstance(existing.state, dict) else {}
            if (
                existing.json_schema != input.output_schema
                or existing_state.get("staged_mcp_scope_preset", "read_only") != input.mcp_scope_preset
            ):
                raise _invalid("staged_task_identity_mismatch")
            analysis_run = (
                TaskRun.objects.select_for_update(of=("self",))
                .filter(task_id=existing.id, team_id=input.team_id, state__staged_phase="analysis")
                .first()
            )
            if analysis_run is None:
                raise _invalid("staged_task_identity_mismatch")
            _validate_run_identity(analysis_run, existing, input.team_id)
            analysis_state = analysis_run.state if isinstance(analysis_run.state, dict) else {}
            if analysis_state.get("context_window") != context_window:
                raise _invalid("staged_task_identity_mismatch")
            return contracts.CreatedStagedTaskDTO(
                task_id=existing.id, analysis_run_id=analysis_run.id, team_id=input.team_id
            )

        try:
            origin_product = Task.OriginProduct(input.origin_product)
        except ValueError as error:
            raise _invalid("staged_task_origin_invalid") from error
        task = Task.objects.create(
            team_id=input.team_id,
            created_by_id=input.actor_id,
            title=input.title,
            description=input.description,
            origin_product=origin_product,
            repository=input.repository,
            github_integration=github_integration,
            origin_key=input.idempotency_key,
            json_schema=input.output_schema,
            internal=True,
            state={
                "staged_caller_id": caller_id,
                "staged_idempotency_key": input.idempotency_key,
                "staged_mcp_scope_preset": input.mcp_scope_preset,
                **(
                    {
                        "staged_repository_grant": {
                            "repository": input.repository_grant.repository,
                            "github_integration_id": input.repository_grant.github_integration_id,
                            "github_installation_id": input.repository_grant.github_installation_id,
                            "grant_version": input.repository_grant.grant_version,
                        }
                    }
                    if input.repository_grant is not None
                    else {}
                ),
                **(
                    {
                        "staged_repository_base": {
                            "repository": input.repository_base.repository,
                            "base_sha": input.repository_base.base_sha,
                            "base_branch": input.repository_base.base_branch,
                        }
                    }
                    if input.repository_base is not None
                    else {}
                ),
            },
        )
        analysis_run = TaskRun.objects.create(
            task=task,
            team_id=input.team_id,
            status=TaskRun.Status.QUEUED,
            queued_at=django_timezone.now(),
            state={
                "mode": "background",
                "staged_phase": "analysis",
                "staged_manifest": _manifest_payload(
                    input.analysis_manifest,
                    caller_id=caller_id,
                    task_id=str(task.id),
                    run_id="pending",
                    publication_allowed=False,
                ),
                "credential_free_checkout": input.repository is not None,
                **(
                    {
                        "staged_repository": input.repository_base.repository,
                        "staged_base_sha": input.repository_base.base_sha,
                        "staged_base_branch": input.repository_base.base_branch,
                    }
                    if input.repository_base is not None
                    else {}
                ),
                "create_pr": False,
                "auto_publish": False,
                **({"context_window": context_window} if context_window is not None else {}),
                "posthog_mcp_scopes": input.mcp_scope_preset,
                "pending_dispatch": _staged_dispatch_intent(input.actor_id, input.mcp_scope_preset),
            },
        )
        state = dict(analysis_run.state)
        state["staged_manifest"] = _manifest_payload(
            input.analysis_manifest,
            caller_id=caller_id,
            task_id=str(task.id),
            run_id=str(analysis_run.id),
            publication_allowed=False,
        )
        analysis_run.state = state
        analysis_run.save(update_fields=["state", "updated_at"])
        transaction.on_commit(lambda: _schedule_staged_run(str(analysis_run.id)))
        return contracts.CreatedStagedTaskDTO(task_id=task.id, analysis_run_id=analysis_run.id, team_id=input.team_id)


def get_staged_task_by_idempotency(
    input: contracts.GetStagedTaskByIdempotencyInput,
) -> contracts.CreatedStagedTaskDTO | None:
    """Resolve only the exact staged analysis task owned by a caller binding."""
    try:
        task = Task.objects.get(team_id=input.team_id, origin_key=input.idempotency_key)
    except Task.DoesNotExist:
        return None
    except Task.MultipleObjectsReturned as error:
        raise _invalid("staged_task_identity_mismatch") from error
    _validate_task_identity(
        task,
        team_id=input.team_id,
        caller_id=str(input.caller_id),
        idempotency_key=input.idempotency_key,
    )
    try:
        analysis_run = TaskRun.objects.get(
            task_id=task.id,
            team_id=input.team_id,
            state__staged_phase="analysis",
        )
    except (TaskRun.DoesNotExist, TaskRun.MultipleObjectsReturned) as error:
        raise _invalid("staged_task_identity_mismatch") from error
    _validate_run_identity(analysis_run, task, input.team_id)
    return contracts.CreatedStagedTaskDTO(
        task_id=task.id,
        analysis_run_id=analysis_run.id,
        team_id=input.team_id,
    )


def get_staged_execution_by_idempotency(
    input: contracts.GetStagedExecutionByIdempotencyInput,
) -> contracts.AdvancedStagedTaskDTO | None:
    """Resolve one caller-bound staged successor without creating or activating work."""
    task = Task.objects.filter(id=input.task_id).first()
    if task is None:
        return None
    state = task.state if isinstance(task.state, dict) else {}
    if task.team_id != input.team_id or state.get("staged_caller_id") != str(input.caller_id):
        raise _invalid("staged_task_identity_mismatch")
    try:
        source_run = TaskRun.objects.get(id=input.source_run_id)
    except TaskRun.DoesNotExist as error:
        raise _invalid("staged_task_identity_mismatch") from error
    _validate_run_identity(source_run, task, input.team_id)
    try:
        transition = TaskStagedRunTransition.objects.for_team(input.team_id).get(
            caller_id=input.caller_id,
            task_id=task.id,
            source_task_run_id=source_run.id,
            idempotency_key=input.idempotency_key,
        )
    except TaskStagedRunTransition.DoesNotExist:
        return None
    _validate_transition_identity(
        transition,
        task=task,
        source_run=source_run,
        team_id=input.team_id,
        caller_id=str(input.caller_id),
    )
    if transition.status != TaskStagedRunTransition.Status.ADVANCED or transition.successor_task_run_id is None:
        raise _invalid("staged_task_identity_mismatch")
    try:
        successor_run = TaskRun.objects.get(id=transition.successor_task_run_id)
    except TaskRun.DoesNotExist as error:
        raise _invalid("staged_task_identity_mismatch") from error
    _validate_run_identity(successor_run, task, input.team_id)
    try:
        lease = TaskPublicationLease.objects.for_team(input.team_id).get(staged_run_transition_id=transition.id)
    except TaskPublicationLease.DoesNotExist:
        lease = None
    if lease is not None:
        _validate_lease_identity(
            lease,
            transition=transition,
            successor_run=successor_run,
            team_id=input.team_id,
            caller_id=str(input.caller_id),
        )
    return contracts.AdvancedStagedTaskDTO(
        task_id=task.id,
        analysis_run_id=source_run.id,
        execution_run_id=successor_run.id,
        transition_id=transition.id,
        publication_lease_id=lease.id if lease is not None else None,
        team_id=input.team_id,
    )


def advance_staged_task(input: contracts.AdvanceStagedTaskInput) -> contracts.AdvancedStagedTaskDTO:
    """Create or recover one staged successor when concurrent callers share an idempotency key."""
    try:
        return _advance_staged_task_once(input)
    except IntegrityError:
        return _advance_staged_task_once(input)


def _advance_staged_task_once(input: contracts.AdvanceStagedTaskInput) -> contracts.AdvancedStagedTaskDTO:
    """Create exactly one execution TaskRun after a durable caller reservation."""
    _validate_manifest(input.execution_manifest, "execution")
    capabilities = frozenset(input.execution_manifest.capabilities)
    publication_required = input.reservation is not None
    if "draft" in capabilities and not publication_required:
        raise _invalid("staged_task_reservation_required")
    if not publication_required and "experiment_draft" not in capabilities:
        raise _invalid("staged_task_execution_capability_required")
    caller_id = str(input.caller_id)
    result: contracts.AdvancedStagedTaskDTO | None = None
    lease_expired = False
    with transaction.atomic():
        Team.objects.select_for_update(of=("self",)).get(id=input.team_id)
        task = Task.objects.select_for_update(of=("self",)).get(id=input.task_id)
        _validate_task_identity(task, team_id=input.team_id, caller_id=caller_id, idempotency_key=task.origin_key or "")
        task_grant = _task_repository_grant(task)
        task_base = _task_repository_base(task)
        if task.repository is None:
            if task_grant is not None or task_base is not None or publication_required:
                raise _invalid("staged_repository_grant_required")
        else:
            if task_grant is None or task_base is None:
                raise _invalid("staged_repository_grant_required")
            _validate_repository_grant_input(task.repository, task_grant, team_id=input.team_id)
        if input.reservation is not None:
            assert task_base is not None
            reservation_grant = contracts.RepositoryGrantBindingDTO(
                repository=input.reservation.repository,
                github_integration_id=input.reservation.github_integration_id,
                github_installation_id=input.reservation.github_installation_id,
                grant_version=input.reservation.grant_version,
            )
            _validate_task_repository_grant(task, reservation_grant)
            if (
                input.reservation.repository != task_base.repository
                or input.reservation.base_sha != task_base.base_sha
                or input.reservation.base_branch != task_base.base_branch
            ):
                raise _invalid("publication_lease_binding_mismatch")
        source_run = TaskRun.objects.select_for_update(of=("self",)).get(id=input.source_run_id)
        _validate_run_identity(source_run, task, input.team_id)
        if source_run.status in _TERMINAL_SOURCE_STATUSES:
            raise _invalid("staged_task_source_not_ready")
        source_state = source_run.state if isinstance(source_run.state, dict) else {}
        context_window = _validate_context_window(source_state.get("context_window"))
        if source_state.get("sandbox_backend") == "hogland":
            raise _invalid("workspace_snapshot_unsupported")
        snapshot_ref = source_state.get("snapshot_external_id")
        if not isinstance(snapshot_ref, str) or not snapshot_ref:
            raise _invalid("workspace_snapshot_required")
        current_time = django_timezone.now()
        transition = (
            TaskStagedRunTransition.objects.for_team(input.team_id)
            .select_for_update(of=("self",))
            .filter(task_id=task.id)
            .first()
        )
        if transition is not None:
            _validate_transition_identity(
                transition,
                task=task,
                source_run=source_run,
                team_id=input.team_id,
                caller_id=caller_id,
            )
            if transition.idempotency_key != input.idempotency_key:
                raise _invalid("staged_task_transition_conflict")
            if transition.successor_task_run_id is None:
                raise _invalid("staged_task_identity_mismatch")
            successor_run = TaskRun.objects.select_for_update(of=("self",)).get(id=transition.successor_task_run_id)
            _validate_run_identity(successor_run, task, input.team_id)
            successor_state = successor_run.state if isinstance(successor_run.state, dict) else {}
            expected_manifest = _manifest_payload(
                input.execution_manifest,
                caller_id=caller_id,
                task_id=str(task.id),
                run_id=str(successor_run.id),
                publication_allowed=publication_required,
            )
            if (
                successor_state.get("staged_manifest") != expected_manifest
                or transition.requested_capability_manifest != expected_manifest
                or successor_state.get("context_window") != context_window
            ):
                raise _invalid("staged_task_transition_conflict")
            lease = (
                TaskPublicationLease.objects.for_team(input.team_id)
                .select_for_update(of=("self",))
                .filter(staged_run_transition_id=transition.id)
                .first()
            )
            if publication_required:
                if lease is None or input.reservation is None:
                    raise _invalid("staged_task_identity_mismatch")
                _validate_lease_identity(
                    lease,
                    transition=transition,
                    successor_run=successor_run,
                    team_id=input.team_id,
                    caller_id=caller_id,
                )
                _validate_lease_bindings(lease, input.reservation)
                if lease.head_branch != f"codex/{lease.id.hex}":
                    raise _invalid("publication_lease_binding_mismatch")
                if lease.status == TaskPublicationLease.Status.ACTIVE and lease.expires_at <= current_time:
                    expired = (
                        TaskPublicationLease.objects.for_team(input.team_id)
                        .filter(id=lease.id, status=TaskPublicationLease.Status.ACTIVE, expires_at__lte=current_time)
                        .update(status=TaskPublicationLease.Status.EXPIRED, expired_at=current_time)
                    )
                    lease_expired = bool(expired)
                if not lease_expired and lease.status != TaskPublicationLease.Status.ACTIVE:
                    raise _invalid("publication_lease_inactive")
            elif lease is not None:
                raise _invalid("staged_task_identity_mismatch")
            if not lease_expired:
                result = contracts.AdvancedStagedTaskDTO(
                    task_id=task.id,
                    analysis_run_id=source_run.id,
                    execution_run_id=successor_run.id,
                    transition_id=transition.id,
                    publication_lease_id=lease.id if lease is not None else None,
                    team_id=input.team_id,
                )
        else:
            reservation = input.reservation
            effective_expiry = None
            effective_starts_before = None
            expected_github_app_slug = ""
            expected_github_app_login = ""
            if reservation is not None:
                if (
                    not _is_safe_branch_ref(reservation.base_branch)
                    or not django_timezone.is_aware(reservation.starts_before)
                    or not django_timezone.is_aware(reservation.expires_at)
                    or reservation.starts_before <= current_time
                    or reservation.starts_before >= reservation.expires_at
                ):
                    raise _invalid("staged_task_reservation_start_cutoff")
                _validate_publication_metadata(reservation)
                github_app_identity = _expected_github_app_identity()
                expected_github_app_slug = github_app_identity.slug
                expected_github_app_login = github_app_identity.login
                if reservation.expires_at <= current_time:
                    raise _invalid("staged_task_reservation_expired")
                effective_expiry = min(reservation.expires_at, current_time + MAX_STAGED_PUBLICATION_LEASE_LIFETIME)
                effective_starts_before = min(
                    reservation.starts_before,
                    effective_expiry - MIN_STAGED_PUBLICATION_FINALIZATION_MARGIN,
                )
                if effective_starts_before <= current_time:
                    raise _invalid("staged_task_reservation_start_cutoff")
            task_state = task.state if isinstance(task.state, dict) else {}
            mcp_scope_preset = task_state.get("staged_mcp_scope_preset", "read_only")
            if mcp_scope_preset not in {"read_only", "pulse_analysis"}:
                raise _invalid("staged_task_mcp_scope_invalid")
            successor_run = TaskRun.objects.create(
                task=task,
                team_id=input.team_id,
                status=TaskRun.Status.QUEUED,
                queued_at=django_timezone.now(),
                state={
                    "mode": "background",
                    "staged_phase": "execution",
                    "resume_from_run_id": str(source_run.id),
                    "snapshot_external_id": snapshot_ref,
                    "snapshot_kind": source_state.get("snapshot_kind", "directory"),
                    "snapshot_mount_path": source_state.get("snapshot_mount_path"),
                    "credential_free_checkout": task.repository is not None,
                    **(
                        {
                            "staged_repository": task_base.repository,
                            "staged_base_sha": task_base.base_sha,
                            "staged_base_branch": task_base.base_branch,
                        }
                        if task_base is not None
                        else {}
                    ),
                    "brokered_publication": publication_required,
                    "create_pr": False,
                    "auto_publish": False,
                    **({"context_window": context_window} if context_window is not None else {}),
                    "posthog_mcp_scopes": mcp_scope_preset,
                    "pending_dispatch": _staged_dispatch_intent(None, mcp_scope_preset),
                },
            )
            requested_manifest = _manifest_payload(
                input.execution_manifest,
                caller_id=caller_id,
                task_id=str(task.id),
                run_id=str(successor_run.id),
                publication_allowed=publication_required,
            )
            transition = TaskStagedRunTransition.objects.for_team(input.team_id).create(
                team_id=input.team_id,
                caller_id=input.caller_id,
                task=task,
                source_task_run=source_run,
                successor_task_run=successor_run,
                source_workspace_snapshot_ref=snapshot_ref,
                requested_capability_manifest=requested_manifest,
                status=TaskStagedRunTransition.Status.ADVANCED,
                idempotency_key=input.idempotency_key,
            )
            lease = None
            if reservation is not None:
                assert effective_starts_before is not None and effective_expiry is not None
                lease = TaskPublicationLease(
                    team_id=input.team_id,
                    caller_id=input.caller_id,
                    task=task,
                    staged_run_transition=transition,
                    task_run=successor_run,
                    logical_artifact_key=reservation.logical_artifact_key,
                    idempotency_key=input.idempotency_key,
                    repository=reservation.repository,
                    base_sha=reservation.base_sha,
                    base_branch=reservation.base_branch,
                    commit_message=reservation.commit_message,
                    pr_title=reservation.pr_title,
                    pr_body=reservation.pr_body,
                    commit_author_name=_PUBLICATION_COMMIT_AUTHOR_NAME,
                    commit_author_email=_PUBLICATION_COMMIT_AUTHOR_EMAIL,
                    commit_timestamp=int(current_time.timestamp()),
                    head_branch="",
                    expected_github_app_slug=expected_github_app_slug,
                    expected_github_app_login=expected_github_app_login,
                    github_integration_id=reservation.github_integration_id,
                    github_installation_id=reservation.github_installation_id,
                    action_key=reservation.action_key,
                    grant_version=reservation.grant_version,
                    starts_before=effective_starts_before,
                    expires_at=effective_expiry,
                )
                lease.head_branch = f"codex/{lease.id.hex}"
                lease.save()
            successor_state = dict(successor_run.state)
            successor_state["staged_manifest"] = requested_manifest
            successor_state["staged_transition_id"] = str(transition.id)
            if lease is not None:
                successor_state["publication_lease_id"] = str(lease.id)
            successor_run.state = successor_state
            successor_run.save(update_fields=["state", "updated_at"])
            transaction.on_commit(lambda: _schedule_staged_run(str(successor_run.id)))
            result = contracts.AdvancedStagedTaskDTO(
                task_id=task.id,
                analysis_run_id=source_run.id,
                execution_run_id=successor_run.id,
                transition_id=transition.id,
                publication_lease_id=lease.id if lease is not None else None,
                team_id=input.team_id,
            )
    if lease_expired:
        raise _invalid("publication_lease_expired")
    assert result is not None
    return result


def revoke_staged_task_capabilities(
    input: contracts.RevokeStagedTaskCapabilitiesInput,
) -> contracts.RevokeStagedTaskCapabilitiesDTO:
    """CAS-revoke pending authority while retaining externally attempted claims for reconciliation."""
    unguarded_task = Task.objects.only("team_id", "github_integration_id").get(id=input.task_id)
    if unguarded_task.team_id != input.team_id:
        raise _invalid("staged_task_identity_mismatch")
    with transaction.atomic():
        Team.objects.select_for_update(of=("self",)).get(id=input.team_id)
        if unguarded_task.github_integration_id is not None:
            try:
                Integration.objects.select_for_update(of=("self",)).get(
                    id=unguarded_task.github_integration_id,
                    team_id=input.team_id,
                    kind=Integration.IntegrationKind.GITHUB,
                )
            except Integration.DoesNotExist as error:
                raise _invalid("staged_repository_grant_inactive") from error
        task = Task.objects.select_for_update(of=("self",)).get(id=input.task_id)
        if task.github_integration_id != unguarded_task.github_integration_id:
            raise _invalid("staged_repository_grant_mismatch")
        caller_id = str(input.caller_id)
        _validate_task_identity(task, team_id=input.team_id, caller_id=caller_id, idempotency_key=task.origin_key or "")
        source_run = TaskRun.objects.select_for_update(of=("self",)).get(id=input.source_run_id)
        _validate_run_identity(source_run, task, input.team_id)
        transition = (
            TaskStagedRunTransition.objects.for_team(input.team_id)
            .select_for_update(of=("self",))
            .filter(task_id=task.id, source_task_run_id=source_run.id)
            .first()
        )
        if transition is None:
            return contracts.RevokeStagedTaskCapabilitiesDTO(revoked=False)
        _validate_transition_identity(
            transition, task=task, source_run=source_run, team_id=input.team_id, caller_id=caller_id
        )
        if transition.successor_task_run_id is None:
            return contracts.RevokeStagedTaskCapabilitiesDTO(revoked=False)
        successor = TaskRun.objects.select_for_update(of=("self",)).get(id=transition.successor_task_run_id)
        _validate_run_identity(successor, task, input.team_id)
        lease = (
            TaskPublicationLease.objects.for_team(input.team_id)
            .select_for_update(of=("self",))
            .filter(staged_run_transition_id=transition.id)
            .first()
        )
        if lease is not None:
            _validate_lease_identity(
                lease, transition=transition, successor_run=successor, team_id=input.team_id, caller_id=caller_id
            )
        publication = None
        if lease is not None:
            publication = (
                TaskDraftPublication.objects.for_team(input.team_id)
                .select_for_update(of=("self",))
                .filter(lease_id=lease.id)
                .first()
            )
        current_time = django_timezone.now()
        retain_external_claim = (
            publication is not None and publication.status in _EXTERNALLY_ATTEMPTED_PUBLICATION_STATUSES
        )
        lease_updated = False
        publication_updated = False
        if lease is not None and not retain_external_claim and lease.status == TaskPublicationLease.Status.ACTIVE:
            if lease.expires_at <= current_time:
                lease_updated = bool(
                    TaskPublicationLease.objects.for_team(input.team_id)
                    .filter(id=lease.id, status=TaskPublicationLease.Status.ACTIVE)
                    .update(status=TaskPublicationLease.Status.EXPIRED, expired_at=current_time)
                )
            else:
                lease_updated = bool(
                    TaskPublicationLease.objects.for_team(input.team_id)
                    .filter(id=lease.id, status=TaskPublicationLease.Status.ACTIVE)
                    .update(status=TaskPublicationLease.Status.REVOKED, revoked_at=current_time)
                )
        if (
            publication is not None
            and not retain_external_claim
            and publication.status
            in {
                TaskDraftPublication.Status.RESERVED,
                TaskDraftPublication.Status.UPLOADED,
                TaskDraftPublication.Status.COMMIT_CREATED,
                TaskDraftPublication.Status.BLOCKED,
            }
        ):
            if lease_updated or (lease is not None and lease.status != TaskPublicationLease.Status.ACTIVE):
                publication.status = TaskDraftPublication.Status.REVOKED
                publication.revoked_at = current_time
                publication.save(update_fields=["status", "revoked_at", "updated_at"])
                publication_updated = True
        transition_updated = False
        if not retain_external_claim:
            transition_updated = bool(
                TaskStagedRunTransition.objects.for_team(input.team_id)
                .filter(id=transition.id, status=TaskStagedRunTransition.Status.ADVANCED)
                .update(status=TaskStagedRunTransition.Status.CANCELLED)
            )
        successor_state = dict(successor.state or {})
        state_updated = successor_state.get("staged_capabilities_revoked") is not True
        if state_updated:
            successor_state["staged_capabilities_revoked"] = True
            successor.state = successor_state
            successor.save(update_fields=["state", "updated_at"])
        return contracts.RevokeStagedTaskCapabilitiesDTO(
            revoked=lease_updated or publication_updated or transition_updated or state_updated
        )


def revoke_staged_capabilities_for_terminal_run(run_id: str) -> bool:
    """Revoke a staged capability after a failure, cancellation, or timeout marker."""
    run = TaskRun.objects.only("id").get(id=run_id)
    transition = (
        TaskStagedRunTransition.objects.unscoped()
        .filter(Q(source_task_run_id=run.id) | Q(successor_task_run_id=run.id))
        .first()
    )
    if transition is None:
        return False
    return _revoke_staged_capabilities_in_global_lock_order(run.id, transition.id)


def terminalize_staged_task_run(
    run_id: str,
    *,
    status: str,
    error_message: str | None = None,
) -> bool:
    """Terminalize a staged run and revoke its capability in the global lock order."""
    run = TaskRun.objects.only("id").get(id=run_id)
    transition = (
        TaskStagedRunTransition.objects.unscoped()
        .filter(Q(source_task_run_id=run.id) | Q(successor_task_run_id=run.id))
        .first()
    )
    if transition is None:
        return False
    return _revoke_staged_capabilities_in_global_lock_order(
        run.id, transition.id, terminal_status=status, error_message=error_message
    )


def _revoke_staged_capabilities_in_global_lock_order(
    run_id: UUID,
    transition_id: UUID,
    *,
    terminal_status: str | None = None,
    error_message: str | None = None,
) -> bool:
    unguarded_transition = (
        TaskStagedRunTransition.objects.unscoped()
        .only("team_id", "task_id", "source_task_run_id")
        .get(id=transition_id)
    )
    unguarded_task = Task.objects.only("team_id", "github_integration_id").get(id=unguarded_transition.task_id)
    if unguarded_task.team_id != unguarded_transition.team_id:
        raise _invalid("staged_task_identity_mismatch")
    with transaction.atomic():
        Team.objects.select_for_update(of=("self",)).get(id=unguarded_transition.team_id)
        if unguarded_task.github_integration_id is not None:
            try:
                Integration.objects.select_for_update(of=("self",)).get(
                    id=unguarded_task.github_integration_id,
                    team_id=unguarded_transition.team_id,
                    kind=Integration.IntegrationKind.GITHUB,
                )
            except Integration.DoesNotExist as error:
                raise _invalid("staged_repository_grant_inactive") from error
        task = Task.objects.select_for_update(of=("self",)).get(id=unguarded_transition.task_id)
        if task.github_integration_id != unguarded_task.github_integration_id:
            raise _invalid("staged_repository_grant_mismatch")
        source_run = TaskRun.objects.select_for_update(of=("self",)).get(id=unguarded_transition.source_task_run_id)
        transition = TaskStagedRunTransition.objects.unscoped().select_for_update(of=("self",)).get(id=transition_id)
        successor_run = None
        if transition.successor_task_run_id is not None:
            successor_run = TaskRun.objects.select_for_update(of=("self",)).get(id=transition.successor_task_run_id)
        lease = (
            TaskPublicationLease.objects.unscoped()
            .select_for_update(of=("self",))
            .filter(staged_run_transition_id=transition.id)
            .first()
        )
        run = source_run if source_run.id == run_id else successor_run
        if run is None or run.id != run_id:
            raise _invalid("staged_task_identity_mismatch")
        caller_id = str(transition.caller_id)
        _validate_task_identity(
            task, team_id=transition.team_id, caller_id=caller_id, idempotency_key=task.origin_key or ""
        )
        _validate_run_identity(source_run, task, transition.team_id)
        _validate_transition_identity(
            transition, task=task, source_run=source_run, team_id=transition.team_id, caller_id=caller_id
        )
        if successor_run is not None:
            _validate_run_identity(successor_run, task, transition.team_id)
        if lease is not None and successor_run is not None:
            _validate_lease_identity(
                lease,
                transition=transition,
                successor_run=successor_run,
                team_id=transition.team_id,
                caller_id=caller_id,
            )
        if terminal_status is not None:
            if run.status not in _TERMINAL_SOURCE_STATUSES or run.status == terminal_status:
                run.status = terminal_status
                run.error_message = error_message or run.error_message
                run.completed_at = django_timezone.now()
                run.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        run_state = run.state if isinstance(run.state, dict) else {}
        if run.status not in _TERMINAL_SOURCE_STATUSES and not any(
            run_state.get(marker) is True for marker in _STAGED_REVOCATION_MARKERS
        ):
            return False
        result = revoke_staged_task_capabilities(
            contracts.RevokeStagedTaskCapabilitiesInput(
                team_id=transition.team_id,
                caller_id=transition.caller_id,
                task_id=transition.task_id,
                source_run_id=transition.source_task_run_id,
            )
        )
        return result.revoked
