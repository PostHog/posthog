"""The one place the stack service calls the engine package.

Everything the service needs from an engine record goes through here, so the service never parses one.
Tests fake the engine by replacing the functions of this module.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from products.stacks.backend.engine.types import (
        Binding,
        ClaimedEntity,
        Credentials,
        EngineOptions,
        StackDescription,
    )

JsonObject = dict[str, Any]


def abort_run() -> type[Exception]:
    """The exception that stops a push from inside `on_record`, when the worker has lost its lease."""
    from products.stacks.backend.engine import AbortRun  # noqa: PLC0415

    return AbortRun


class EngineFailure(Exception):
    """The engine refused the input. `errors` are diff errors in stack words."""

    def __init__(self, errors: list[JsonObject]) -> None:
        super().__init__(" ".join(str(error.get("message", "")) for error in errors))
        self.errors = errors


@frozen
class EngineCredentials:
    host: str
    project_id: int
    api_key: str = field(repr=False)
    # The values of the secrets the description names, and no others.
    secrets: dict[str, str] = field(default_factory=dict, repr=False)


@frozen
class BindingRecord:
    kind: str
    key: str
    entity_id: str


@frozen
class DiffOutcome:
    diff: JsonObject
    saved_diff: bytes


@frozen
class PushOutcome:
    errors: list[JsonObject]
    record: bytes
    # (kind, key) of the bindings the engine marked as adopted.
    adopted: frozenset[tuple[str, str]] = frozenset()


@frozen
class EntityPageItem:
    entity_id: str
    name: str
    body: JsonObject


@frozen
class EntityPage:
    results: list[EntityPageItem]
    next_cursor: str | None


def _options() -> EngineOptions:
    options: EngineOptions = {"binary": settings.STACKS_ENGINE_BINARY}
    if settings.STACKS_ENGINE_MIRROR:
        options["mirror"] = settings.STACKS_ENGINE_MIRROR
    elif settings.STACKS_ENGINE_ALLOW_REGISTRY:
        options["allow_registry"] = True
    return options


def workdir() -> Path:
    return Path(settings.STACKS_ENGINE_WORKDIR)


def _credentials(credentials: EngineCredentials) -> Credentials:
    engine_credentials: Credentials = {
        "host": credentials.host,
        "project_id": credentials.project_id,
        "api_key": credentials.api_key,
    }
    if credentials.secrets:
        engine_credentials["secrets"] = dict(credentials.secrets)
    return engine_credentials


def _errors(error: Any) -> list[JsonObject]:
    return [dict(item) for item in error.errors]


def build_input(description: JsonObject, bindings: list[JsonObject], claimed: list[JsonObject]) -> Any:
    """The engine input for a description.

    `bindings` are this stack's `{kind, key, entity_id, status, origin}` dicts. `claimed` are the entities other
    stacks in the team manage, as `{kind, entity_id, stack, repository}` dicts, so the engine refuses to adopt one.
    """
    # The engine package runs subprocesses and loads its mapping files, so web requests import it only when they
    # need it.
    from products.stacks.backend.engine import EngineError, translate_in  # noqa: PLC0415

    try:
        options = _options()
        options["claimed"] = cast("list[ClaimedEntity]", claimed)
        return translate_in(cast("StackDescription", description), cast("list[Binding]", bindings), options)
    except EngineError as error:
        raise EngineFailure(_errors(error)) from error


def diff(engine_input: Any, record: bytes | None, credentials: EngineCredentials) -> DiffOutcome:
    from products.stacks.backend.engine import EngineError, run_diff  # noqa: PLC0415

    try:
        result, saved_diff, _serial = run_diff(workdir(), engine_input, record, _credentials(credentials))
    except EngineError as error:
        raise EngineFailure(_errors(error)) from error
    return DiffOutcome(diff=dict(result), saved_diff=saved_diff)


def push(
    engine_input: Any,
    saved_diff: bytes,
    record: bytes | None,
    credentials: EngineCredentials,
    on_record: Callable[[bytes], None],
) -> PushOutcome:
    """Push a saved diff. `on_record` receives the stack's record each time the engine rewrites it."""
    from products.stacks.backend.engine import EngineError, run_push  # noqa: PLC0415

    # Without `on_record` a worker that dies mid-push loses what already succeeded, so such a build never pushes.
    if "on_record" not in inspect.signature(run_push).parameters:
        raise EngineFailure(
            [{"code": "runner_unavailable", "message": "The stack worker needs an update. Try again later."}]
        )
    try:
        result, new_record = run_push(
            workdir(), engine_input, saved_diff, record, _credentials(credentials), on_record=on_record
        )
    except EngineError as error:
        # What the push changed before the error reached the service through `on_record`.
        return PushOutcome(errors=_errors(error), record=b"")
    adopted = frozenset(
        (str(binding["kind"]), str(binding["key"]))
        for binding in result.get("bindings", [])
        if binding.get("origin") == "adopted"
    )
    return PushOutcome(errors=[dict(item) for item in result.get("errors", [])], record=new_record, adopted=adopted)


def bindings_in(record: bytes) -> list[BindingRecord]:
    from products.stacks.backend.engine import read_bindings  # noqa: PLC0415

    return [
        BindingRecord(kind=binding["kind"], key=binding["key"], entity_id=str(binding["entity_id"]))
        for binding in read_bindings(record)
    ]


def read_entities(
    kind: str,
    credentials: EngineCredentials,
    *,
    ids: list[str] | None = None,
    cursor: str | None = None,
    limit: int = 100,
) -> EntityPage:
    """Entities of a kind in PostHog, read with the caller's credential, with bodies in description shape."""
    from products.stacks.backend.engine import (  # noqa: PLC0415
        EngineError,
        read_entities as engine_read_entities,
    )

    try:
        page = engine_read_entities(kind, _credentials(credentials), ids=ids, cursor=cursor, limit=limit)
    except EngineError as error:
        raise EngineFailure(_errors(error)) from error
    return EntityPage(
        results=[
            EntityPageItem(entity_id=str(item["entity_id"]), name=str(item.get("name") or ""), body=dict(item["body"]))
            for item in page["results"]
        ],
        next_cursor=page.get("next_cursor"),
    )


def validate_description(description: JsonObject, bindings: list[JsonObject]) -> list[JsonObject]:
    """Errors in a description, found without running anything. The service calls it before storing anything."""
    from products.stacks.backend.engine import validate_description as engine_validate  # noqa: PLC0415

    return [
        dict(error) for error in engine_validate(cast("StackDescription", description), cast("list[Binding]", bindings))
    ]


def validate_key(kind: str, key: str) -> JsonObject | None:
    """The error for a key the kind's own naming rule refuses, or None."""
    from products.stacks.backend.engine import validate_key as engine_validate_key  # noqa: PLC0415

    error = engine_validate_key(kind, key)
    return dict(error) if error is not None else None


def kind_scopes(kind: str) -> dict[str, list[str]]:
    """The scopes a run needs to read a kind, and to write it. The write list includes the read grants."""
    from products.stacks.backend.engine import (  # noqa: PLC0415
        EngineError,
        kind_scopes as engine_kind_scopes,
    )

    try:
        scopes = engine_kind_scopes(kind)
    except EngineError as error:
        raise EngineFailure(_errors(error)) from error
    return {"read": list(scopes["read"]), "write": list(scopes["write"])}


def mapped_kinds() -> list[str]:
    from products.stacks.backend.engine.mappings import mappings  # noqa: PLC0415

    return sorted(mappings())


def ownership_scope(kind: str) -> str:
    """ "organization" for a kind every project of an organization shares, such as a context page, else "team"."""
    from products.stacks.backend.engine.mappings import mappings  # noqa: PLC0415

    return str(mappings().get(kind, {}).get("ownership_scope", "team"))


def natural_key_kinds() -> frozenset[str]:
    """Kinds whose key is the entity's own natural key, so two stacks with one key claim one entity."""
    from products.stacks.backend.engine import natural_key_kinds as engine_natural_key_kinds  # noqa: PLC0415

    return frozenset(engine_natural_key_kinds())


def owned_fields(kind: str, body: JsonObject) -> frozenset[str]:
    """The body paths, possibly dotted, that code owns for a bound definition with this body."""
    from products.stacks.backend.engine import (  # noqa: PLC0415
        EngineError,
        owned_fields as engine_owned_fields,
    )

    try:
        return frozenset(engine_owned_fields(kind, body))
    except EngineError:
        return frozenset()
