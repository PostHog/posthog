from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

Json = str | int | float | bool | None | list["Json"] | dict[str, "Json"]
Action = Literal["create", "update", "recreate", "remove", "adopt", "rename", "release"]
ACTIONS: tuple[Action, ...] = ("create", "update", "recreate", "remove", "adopt", "rename", "release")


class Source(TypedDict):
    file: str
    export: NotRequired[str]


class Identity(TypedDict):
    kind: str
    key: str


class ResourceDescription(Identity):
    body: dict[str, Json]
    source: NotRequired[Source]
    depends_on: NotRequired[list[Identity]]


class StackDescription(TypedDict):
    version: Literal[1]
    resources: list[ResourceDescription]


class Entity(TypedDict):
    entity_id: str
    name: str
    body: dict[str, Json]


class EntityPage(TypedDict):
    results: list[Entity]
    next_cursor: str | None


class BindingRecord(Identity):
    entity_id: str | int
    origin: NotRequired[Literal["created", "adopted"]]


class Binding(BindingRecord):
    status: NotRequired[Literal["pending", "bound", "detached"]]


class ClaimedEntity(TypedDict):
    kind: str
    entity_id: str | int
    stack: str
    repository: str


class FieldChange(TypedDict):
    path: str
    before: Json
    after: Json
    sensitive: bool


class Change(Identity):
    action: Action
    entity_id: NotRequired[str]
    name: str
    summary: str
    fields: list[FieldChange]
    source: Source | None
    loses: str | None


class DriftField(TypedDict):
    path: str
    pushed: Json
    found: Json
    sensitive: NotRequired[bool]


class Drift(Identity):
    fields: list[DriftField]
    deleted: NotRequired[Literal[True]]


class DiffError(TypedDict):
    code: str
    message: str
    kind: NotRequired[str]
    key: NotRequired[str]
    path: NotRequired[str]


class Diff(TypedDict):
    changes: list[Change]
    drift: list[Drift]
    summary: dict[Action, int]
    errors: list[DiffError]


class PushResult(TypedDict):
    errors: list[DiffError]
    bindings: list[BindingRecord]


class EngineOptions(TypedDict, total=False):
    mirror: str | Path
    binary: str | Path
    allow_registry: bool
    refresh: bool
    rename_map: dict[str, Identity]
    detach: list[Identity]
    existing: list[BindingRecord]
    claimed: list[ClaimedEntity]
    timeout_seconds: float


class Credentials(TypedDict):
    host: str
    project_id: str | int
    api_key: str
    secrets: NotRequired[Mapping[str, str]]


@dataclass(frozen=True, kw_only=True, slots=True)
class EngineInput:
    config: dict[str, Any] = field(repr=False)
    description: StackDescription = field(repr=False)
    options: EngineOptions = field(default_factory=EngineOptions)
    secret_names: frozenset[str] = frozenset()
    adopted_ids: frozenset[tuple[str, str]] = frozenset()
    import_entity_ids: dict[str, str | int] = field(default_factory=dict)


class EngineError(ValueError):
    def __init__(self, errors: list[DiffError]) -> None:
        self.errors = errors
        super().__init__(" ".join(error["message"] for error in errors))
