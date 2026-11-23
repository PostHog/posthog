"""
Facade for stacks.

The only module other code may import for stack data. It takes and returns contracts and never returns
a model. No function here returns a stack's record of what it made, a saved diff or a secret value.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.paging import Page, PageRequest

from ..logic import (
    adoptable as adoptable_logic,
    change_requests,
    cleanup,
    credentials,
    crypto,
    kinds,
    managed,
    modules,
    pushes,
    reconcile as reconcile_logic,
    stacks,
    validation,
)
from ..models import (
    StackBinding,
    StackDiff as StackDiffModel,
    StackSecret,
)
from . import contracts
from .enums import BindingStatus, DiffStatus, PushStatus


def _visible_status(diff: StackDiffModel) -> DiffStatus:
    """A push runs and fails on a ready diff, so callers read its progress from the same status."""
    if diff.status == DiffStatus.READY.value and diff.push_status == PushStatus.RUNNING.value:
        return DiffStatus.RUNNING
    if diff.status == DiffStatus.READY.value and diff.push_status == PushStatus.FAILED.value:
        return DiffStatus.FAILED
    return DiffStatus(diff.status)


def _to_diff(diff: StackDiffModel, *, with_values: bool) -> contracts.StackDiff:
    return contracts.StackDiff(
        id=diff.id,
        stack_name=diff.stack.name,
        status=_visible_status(diff),
        diff=diff.diff if with_values else validation.without_values(diff.diff),
        source=stacks.diff_source(diff),
        created_at=diff.created_at,
        expires_at=diff.expires_at,
        push_status=PushStatus(diff.push_status) if diff.push_status else None,
        push_errors=list(diff.push_errors or []),
    )


def _may_see_values(diff: StackDiffModel, caller: contracts.Caller) -> bool:
    return caller.is_project_admin or diff.created_by_id == caller.user_id


def _to_binding(binding: StackBinding) -> contracts.Binding:
    return contracts.Binding(
        id=binding.id,
        stack_name=binding.stack.name,
        repository=binding.stack.repository,
        kind=binding.kind,
        key=binding.key,
        entity_id=binding.entity_id,
        status=BindingStatus(binding.status),
        source_file=binding.source_file,
        source_export=binding.source_export,
        owned_fields=tuple(sorted(binding.owned_fields or [])),
    )


def _to_secret(secret: StackSecret) -> contracts.SecretInfo:
    return contracts.SecretInfo(name=secret.name, updated_at=secret.updated_at)


def diff_scopes(*, team_id: int, stack_name: str, description: contracts.JsonObject) -> list[str]:
    """The API scopes a diff of this description reads with, beyond `stack:read`."""
    return stacks.diff_scopes(team_id, stack_name, description, write=False)


def push_scopes(*, team_id: int, stack_name: str, diff_id: UUID, target_team_id: int) -> list[str]:
    """The API scopes a push of this diff uses, beyond `stack:write`."""
    return stacks.push_scopes(team_id, stack_name, diff_id, target_team_id=target_team_id)


def diff_read_scopes(*, team_id: int, stack_name: str, diff_id: UUID, target_team_id: int) -> list[str]:
    """The scopes a reader of this diff needs: the read scopes the diff itself ran with."""
    return kinds.read_scopes(stacks.get_diff(team_id, stack_name, diff_id, target_team_id=target_team_id).run_scopes)


def kind_read_scopes(kinds_used: Iterable[str]) -> list[str]:
    """The scopes needed to read entities of these kinds, for listing adoptable entities."""
    return kinds.run_scopes(kinds_used, write=False)


def kind_write_scopes(kinds_used: Iterable[str]) -> list[str]:
    """The scopes needed to change entities of these kinds, for adopt and detach."""
    return kinds.run_scopes(kinds_used, write=True)


def start_diff(params: contracts.StartDiffInput, *, scopes: list[str]) -> contracts.StackDiff:
    return _to_diff(stacks.start_diff(params, scopes), with_values=True)


def get_diff(*, team_id: int, stack_name: str, diff_id: UUID, caller: contracts.Caller) -> contracts.StackDiff:
    diff = stacks.get_diff(team_id, stack_name, diff_id, target_team_id=caller.target_team_id)
    return _to_diff(diff, with_values=_may_see_values(diff, caller))


def start_push(params: contracts.StartPushInput, *, scopes: list[str]) -> contracts.StackDiff:
    diff = pushes.start_push(params, scopes)
    return _to_diff(diff, with_values=_may_see_values(diff, params.caller))


def reconcile(params: contracts.ReconcileInput) -> contracts.Reconciled:
    """Accept a ready diff computed since an uncertain push, warnings included, so the stack pushes again."""
    stack, acknowledged = reconcile_logic.reconcile(params)
    return contracts.Reconciled(stack_name=stack.name, diff_id=params.diff_id, acknowledged_warnings=acknowledged)


def list_bindings(*, team_id: int, stack_name: str, page: PageRequest) -> Page[contracts.Binding]:
    return stacks.list_bindings(team_id, stack_name, page).map(_to_binding)


def adopt(params: contracts.AdoptInput) -> list[contracts.Binding]:
    stacks.ensure_ready()
    resources = [(resource.kind, resource.key, resource.entity_id) for resource in params.resources]
    canonical = adoptable_logic.canonical_ids(params.caller, resources)
    return [_to_binding(binding) for binding in stacks.adopt(params, canonical)]


def binding_kind(*, team_id: int, stack_name: str, binding_id: UUID) -> str:
    return stacks.get_binding(team_id, stack_name, binding_id).kind


def detach(*, team_id: int, stack_name: str, binding_id: UUID) -> contracts.Binding:
    return _to_binding(stacks.detach(team_id, stack_name, binding_id))


def find_bindings(*, team_id: int, kind: str, entity_id: str) -> list[contracts.Binding]:
    """What manages this entity: one binding, or none."""
    return [_to_binding(binding) for binding in stacks.find_bindings(team_id, kind=kind, entity_id=entity_id)]


def list_adoptable(
    *, team_id: int, caller: contracts.Caller, kind: str, cursor: str | None, limit: int
) -> contracts.AdoptablePage:
    return adoptable_logic.list_adoptable(team_id, caller, kind, cursor=cursor, limit=limit)


def entity_path(*, kind: str, entity_id: str) -> str | None:
    """The app path, under the project, where the entity opens. None for a kind with no such page."""
    return kinds.entity_path(kind, entity_id)


def set_secret(params: contracts.SetSecretInput) -> contracts.SecretInfo:
    return _to_secret(stacks.set_secret(params))


def list_secrets(*, team_id: int, stack_name: str) -> list[contracts.SecretInfo]:
    return [_to_secret(secret) for secret in stacks.list_secrets(team_id, stack_name)]


def delete_secret(*, team_id: int, stack_name: str, name: str) -> None:
    stacks.delete_secret(team_id, stack_name, name)


def reencrypt_records() -> int:
    """Re-encrypt every stored record, saved diff, description and secret onto the primary key."""
    return crypto.reencrypt_all()


def run_cleanup() -> dict[str, int]:
    """One pass of the cleanup schedule: abandoned pushes, timed-out diffs, expired saved diffs, work directories."""
    return cleanup.sweep()


def ensure_ready() -> None:
    """Refuse with `stacks_unavailable` when this instance has no stacks database or no valid encryption key."""
    stacks.ensure_ready()


def check_description_limits(description: contracts.JsonObject) -> None:
    """The size, depth and identity limits of a description, checked before anything reads the stack."""
    validation.check_limits(description)


def delete_data_for_teams(team_ids: list[int]) -> None:
    """Delete the stack data of deleted projects. Safe to call again."""
    cleanup.delete_team_data(team_ids)


def set_context_pages(
    *, team_id: int, stack_name: str, enabled: bool, caller: contracts.Caller
) -> contracts.StackSettings:
    """Let a stack manage context pages, or stop it. Only an organization admin may."""
    stack = stacks.set_context_pages(team_id, stack_name, enabled=enabled, caller=caller)
    return contracts.StackSettings(name=stack.name, context_pages_enabled=stack.context_pages_enabled)


def managed_kinds(*, team_id: int) -> list[contracts.ManagedKind]:
    """Each kind some stack in the project manages, so an agent about to create one is pointed at the code."""
    return [contracts.ManagedKind(**row) for row in managed.managed_kinds(resolve_effective_team_id(team_id))]


def generate_module(*, description: contracts.JsonObject, language: str) -> contracts.GeneratedModule:
    """The typed module for one language that the events of a description give. Stores nothing."""
    return modules.generate(description, language)


def request_change(params: contracts.ChangeRequestInput) -> contracts.StartedChangeRequest:
    """Start a cloud task that edits a managed entity's definition in the stack's repository and opens a pull
    request. Nothing in PostHog changes until that pull request is merged and pushed."""
    return change_requests.request_change(params)


def provision_oauth_app() -> str:
    """Create or update the first-party application stack runs mint their tokens from. Safe to run again."""
    return credentials.provision_stacks_oauth_app().client_id
