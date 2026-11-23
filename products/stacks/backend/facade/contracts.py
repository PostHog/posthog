"""
Contract types for stacks.

Frozen dataclasses that cross the stacks facade. No Django imports.
A stack's record of what it made never appears in a contract, because no caller may read it.
"""

from dataclasses import field
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import JsonValue
from pydantic.dataclasses import dataclass

from .enums import BindingStatus, DiffStatus, PushStatus, StackErrorKind

JsonObject = dict[str, Any]


class StackServiceError(Exception):
    """A refusal that a caller can act on. `message` is written for a person and uses only stack words."""

    def __init__(self, kind: StackErrorKind, code: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CallerGrant:
    """The credential a request authenticated with, as a reference the worker can re-check. Never its secret."""

    type: str  # "session", "personal_api_key", "oauth" or "workload"
    id: str
    # A workload token's policy version and expiry, which the worker compares before every mint.
    version: str = ""
    expires_at: str = ""


@dataclass(frozen=True)
class Caller:
    user_id: int
    grant: CallerGrant
    # The exact project the route resolved and the credential was authorized for.
    target_team_id: int
    organization_id: str
    # The scopes the credential holds, or None when it carries the user's full authority (a session).
    held_scopes: list[str] | None
    # True when the viewer may see field values in any diff of the project.
    is_project_admin: bool = False
    is_organization_admin: bool = False
    impersonated: bool = False


@dataclass(frozen=True)
class DiffSource:
    repository: str
    branch: str
    commit: str


@dataclass(frozen=True)
class StartDiffInput:
    team_id: int
    stack_name: str
    description: JsonObject
    source: DiffSource
    caller: Caller


@dataclass(frozen=True)
class StartPushInput:
    team_id: int
    stack_name: str
    diff_id: UUID
    caller: Caller
    # Overrides the stack's removal cap for this push only.
    max_removals: int | None = None


@dataclass(frozen=True)
class ReconcileInput:
    team_id: int
    stack_name: str
    # A ready diff computed since the uncertain push. Its warnings are what the person acknowledges.
    diff_id: UUID
    caller: Caller


@dataclass(frozen=True)
class Reconciled:
    stack_name: str
    diff_id: UUID
    acknowledged_warnings: int


@dataclass(frozen=True)
class StackDiff:
    id: UUID
    stack_name: str
    status: DiffStatus
    # The diff in the shape the contract fixes: changes, drift, summary, errors. None while running.
    diff: JsonObject | None
    source: DiffSource
    created_at: datetime
    expires_at: datetime
    push_status: PushStatus | None
    push_errors: list[JsonObject]


@dataclass(frozen=True)
class Binding:
    id: UUID
    stack_name: str
    repository: str
    kind: str
    key: str
    entity_id: str
    status: BindingStatus
    source_file: str
    source_export: str
    # The body paths code owns, sorted. Empty when nothing is owned.
    owned_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdoptResource:
    kind: str
    key: str
    entity_id: str


@dataclass(frozen=True)
class AdoptInput:
    team_id: int
    stack_name: str
    caller: Caller
    resources: list[AdoptResource]


@dataclass(frozen=True)
class SecretInfo:
    name: str
    updated_at: datetime


@dataclass(frozen=True)
class SetSecretInput:
    team_id: int
    stack_name: str
    name: str
    value: str = field(repr=False)
    caller: Caller


@dataclass(frozen=True)
class AdoptableEntity:
    kind: str
    entity_id: str
    name: str
    # Shaped like the kind's create body, the same shape as a description resource's body.
    body: JsonObject


@dataclass(frozen=True)
class AdoptablePage:
    results: list[AdoptableEntity]
    next_cursor: str | None


@dataclass(frozen=True)
class StackSettings:
    name: str
    context_pages_enabled: bool


@dataclass(frozen=True)
class ManagedKind:
    kind: str
    stack_name: str
    repository: str
    definitions: int
    # True for a natural-key kind: a create outside code would collide with the code, so the MCP redirects it.
    redirect_creates: bool


@dataclass(frozen=True)
class GeneratedModule:
    content: str
    language: str
    event_count: int
    schema_hash: str
    generator_version: str


@dataclass(frozen=True)
class RequestedChange:
    path: str
    value: JsonValue


@dataclass(frozen=True)
class ChangeRequestInput:
    team_id: int
    stack_name: str
    binding_id: UUID
    caller: Caller
    note: str
    changes: list[RequestedChange]


@dataclass(frozen=True)
class StartedChangeRequest:
    task_id: UUID
    task_url: str
