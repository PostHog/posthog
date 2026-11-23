"""Shared fixtures for stacks tests.

The engine is faked at `engine_adapter`, the one module that calls it, and the Temporal starts are recorded
instead of sent, so a test runs the worker side by calling `logic.runs` itself.

The fake engine keeps its own record of the entities that exist in PostHog (`FakeRemote`), apart from the stack's
record. A push replays the operations its saved diff planned, so a replay that creates a second entity, or a
removal of an entity another stack holds, shows in `remote`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from unittest.mock import patch

from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models.oauth import OAuthAccessToken

from products.stacks.backend import engine_adapter
from products.stacks.backend.engine_adapter import (
    BindingRecord,
    DiffOutcome,
    EngineCredentials,
    EntityPage,
    EntityPageItem,
    PushOutcome,
)

PRODUCT_DATABASES = {"default", "stacks_db_writer", "stacks_db_reader"}
RECORD_SECRET = "record-secret-value"
SAVED_DIFF_SECRET = "saved-diff-secret-value"

# Shaped like the engine's `kind_scopes`: the write list holds the reads too.
KIND_SCOPES = {
    "action": {"read": ["action:read"], "write": ["action:read", "action:write"]},
    "alert": {"read": ["alert:read", "insight:read"], "write": ["alert:read", "alert:write", "insight:read"]},
    "context_page": {"read": ["organization:read"], "write": ["organization:read", "organization:write"]},
    "event": {"read": ["event_definition:read"], "write": ["event_definition:read", "event_definition:write"]},
    "property_group": {"read": ["event_definition:read"], "write": ["event_definition:read", "event_definition:write"]},
    "flag": {"read": ["feature_flag:read"], "write": ["feature_flag:read", "feature_flag:write"]},
    "insight": {"read": ["insight:read"], "write": ["insight:read", "insight:write"]},
    "source": {
        "read": ["external_data_source:read"],
        "write": ["external_data_source:read", "external_data_source:write"],
    },
}
ORGANIZATION_KINDS = frozenset({"context_page"})
NATURAL_KEY_KINDS = frozenset({"flag", "event", "property_group"})


class FakeAbortRun(Exception):
    pass


class WorkerDied(BaseException):
    """Stands for a worker process that dies: no handler in the service sees it."""


class FakeRemote:
    """The entities that exist in PostHog, whatever any stack's record says."""

    def __init__(self) -> None:
        self.entities: dict[tuple[str, str], dict[str, Any]] = {}
        self._next_id = 100

    def add(self, kind: str, body: dict[str, Any], entity_id: str | None = None) -> str:
        if entity_id is None:
            self._next_id += 1
            entity_id = str(self._next_id)
        self.entities[(kind, entity_id)] = dict(body)
        return entity_id

    def of(self, kind: str) -> dict[str, dict[str, Any]]:
        return {entity_id: body for (k, entity_id), body in self.entities.items() if k == kind}

    def natural(self, kind: str, key: str) -> str | None:
        return next((entity_id for entity_id, body in self.of(kind).items() if body.get("key") == key), None)


class FakeEngineInput:
    def __init__(self, description: dict, bindings: list[dict], claimed: list[dict]) -> None:
        self.description = description
        self.bindings = bindings
        self.claimed = claimed


def _entities(record: bytes | None) -> list[dict[str, Any]]:
    return json.loads(record)["entities"] if record else []


def _record(entities: list[dict[str, Any]]) -> bytes:
    return json.dumps({"entities": entities, "secret": RECORD_SECRET}, sort_keys=True).encode()


class FakeEngine:
    def __init__(self) -> None:
        self.remote = FakeRemote()
        self.inputs: list[FakeEngineInput] = []
        self.credentials: list[EngineCredentials] = []
        self.token_scopes: list[str] = []
        self.token_teams: list[list[int]] = []
        self.token_expiries: list[Any] = []
        self.diff_errors: list[dict] = []
        self.extra_removals = 0
        self.extra_recreates = 0
        self.leaked_sensitive = False
        self.die_after: int | None = None
        # The worker dies after the change reached PostHog and before the engine reported it.
        self.die_before_record: int | None = None
        # The engine process is killed after the change reached PostHog and before it reported it.
        self.interrupt_before_record: int | None = None
        self.fail_after: int | None = None
        self.on_each_record: Callable[[int], None] | None = None
        self.during_diff: Callable[[], None] | None = None
        self.drift: list[dict] = []

    def _note(self, credentials: EngineCredentials) -> None:
        token = OAuthAccessToken.objects.get(token=credentials.api_key)
        self.credentials.append(credentials)
        self.token_scopes.append(token.scope)
        self.token_teams.append(list(token.scoped_teams or []))
        self.token_expiries.append(token.expires)

    def build_input(self, description: dict, bindings: list[dict], claimed: list[dict]) -> FakeEngineInput:
        engine_input = FakeEngineInput(description, bindings, claimed)
        self.inputs.append(engine_input)
        return engine_input

    def diff(self, engine_input: FakeEngineInput, record: bytes | None, credentials: EngineCredentials) -> DiffOutcome:
        self._note(credentials)
        if self.during_diff is not None:
            self.during_diff()
        held = {(e["kind"], e["key"]): e for e in _entities(record)}
        bindings = {(b["kind"], b["key"]): b for b in engine_input.bindings}
        claimed = {(c["kind"], str(c["entity_id"])) for c in engine_input.claimed}
        ops: list[dict[str, Any]] = []
        errors = list(self.diff_errors)
        described = set()
        for resource in engine_input.description["resources"]:
            kind, key, body = resource["kind"], resource["key"], resource["body"]
            identity = (kind, key)
            binding = bindings.get(identity)
            if binding is not None and binding["status"] == "detached":
                continue
            described.add(identity)
            if identity in held:
                entity_id = held[identity]["entity_id"]
                if (kind, entity_id) in self.remote.entities:
                    ops.append({"action": "update", "kind": kind, "key": key, "entity_id": entity_id, "body": body})
                else:
                    ops.append({"action": "create", "kind": kind, "key": key, "body": body})
            elif binding is not None and binding["status"] == "pending":
                ops.append({"action": "adopt", "kind": kind, "key": key, "entity_id": binding["entity_id"]})
            elif kind in NATURAL_KEY_KINDS and (existing := self.remote.natural(kind, key)) is not None:
                if (kind, existing) in claimed:
                    errors.append({"code": "claimed_by_other_stack", "message": "Another stack manages it."})
                else:
                    ops.append({"action": "adopt", "kind": kind, "key": key, "entity_id": existing})
            else:
                ops.append({"action": "create", "kind": kind, "key": key, "body": body})
        for identity, entity in sorted(held.items()):
            if identity in described:
                continue
            binding = bindings.get(identity, {})
            released = binding.get("origin") == "adopted" or binding.get("status") == "detached"
            ops.append({"action": "release" if released else "remove", **entity})
        summary = dict.fromkeys(("create", "update", "recreate", "remove", "adopt", "rename", "release"), 0)
        for op in ops:
            summary[op["action"]] += 1
        summary["remove"] += self.extra_removals
        summary["recreate"] += self.extra_recreates
        changes = []
        for op in ops:
            fields = [{"path": "name", "before": None, "after": op["key"], "sensitive": False}]
            if self.leaked_sensitive:
                fields.append({"path": "password", "before": "old-value", "after": "new-value", "sensitive": True})
            change = {
                "action": op["action"],
                "kind": op["kind"],
                "key": op["key"],
                "name": op["key"],
                "summary": op["action"],
                "fields": fields,
                "source": None,
                "loses": None,
            }
            if op["action"] == "adopt":
                change["entity_id"] = op["entity_id"]
            changes.append(change)
        result = {"changes": changes, "drift": list(self.drift), "summary": summary, "errors": errors}
        saved = b"" if errors else json.dumps({"ops": ops, "plan": SAVED_DIFF_SECRET}).encode()
        return DiffOutcome(diff=result, saved_diff=saved)

    def push(
        self,
        engine_input: FakeEngineInput,
        saved_diff: bytes,
        record: bytes | None,
        credentials: EngineCredentials,
        on_record: Callable[[bytes], None],
    ) -> PushOutcome:
        self._note(credentials)
        state = _entities(record)
        adopted: set[tuple[str, str]] = set()
        for index, op in enumerate(json.loads(saved_diff)["ops"], start=1):
            kind, key = op["kind"], op["key"]
            # PostHog's API refuses a revoked token, so a worker whose token was revoked changes nothing more.
            if (
                op["action"] in ("create", "update", "remove")
                and not OAuthAccessToken.objects.filter(token=credentials.api_key).exists()
            ):
                return PushOutcome(errors=[{"code": "unauthorized", "message": "The token was revoked."}], record=b"")
            if op["action"] == "create":
                entity_id = self.remote.add(kind, op["body"])
                state = [e for e in state if (e["kind"], e["key"]) != (kind, key)]
                state.append({"kind": kind, "key": key, "entity_id": entity_id})
            elif op["action"] == "update":
                self.remote.entities[(kind, op["entity_id"])] = dict(op["body"])
            elif op["action"] == "adopt":
                state.append({"kind": kind, "key": key, "entity_id": op["entity_id"]})
                adopted.add((kind, key))
            elif op["action"] == "remove":
                self.remote.entities.pop((kind, op["entity_id"]), None)
                state = [e for e in state if (e["kind"], e["key"]) != (kind, key)]
            elif op["action"] == "release":
                state = [e for e in state if (e["kind"], e["key"]) != (kind, key)]
            if self.die_before_record == index:
                raise WorkerDied
            if self.interrupt_before_record == index:
                return PushOutcome(
                    errors=[{"code": "stack_interrupted", "message": "The stack stopped unexpectedly."}], record=b""
                )
            on_record(_record(state))
            if self.on_each_record is not None:
                self.on_each_record(index)
            if self.die_after == index:
                raise WorkerDied
            if self.fail_after == index:
                return PushOutcome(errors=[{"code": "apply_failed", "message": "One change failed."}], record=b"")
        return PushOutcome(errors=[], record=_record(state), adopted=frozenset(adopted))

    def bindings_in(self, record: bytes) -> list[BindingRecord]:
        return [BindingRecord(kind=e["kind"], key=e["key"], entity_id=e["entity_id"]) for e in _entities(record)]

    def read_entities(
        self,
        kind: str,
        credentials: EngineCredentials,
        *,
        ids: list[str] | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> EntityPage:
        self._note(credentials)
        wanted = {str(int(entity_id)) if entity_id.isdigit() else entity_id for entity_id in ids} if ids else None
        items = [
            EntityPageItem(entity_id=entity_id, name=str(body.get("name", "")), body=body)
            for entity_id, body in sorted(self.remote.of(kind).items())
            if wanted is None or entity_id in wanted
        ]
        return EntityPage(results=items[:limit], next_cursor=None)

    def validate_description(self, description: dict, bindings: list[dict]) -> list[dict]:
        errors = []
        for resource in description.get("resources", []):
            if resource["kind"] not in KIND_SCOPES:
                errors.append({"code": "kind_unsupported", "message": f"No kind {resource['kind']}."})
            password = resource["body"].get("password")
            if resource["kind"] == "source" and password is not None and not isinstance(password, dict):
                errors.append(
                    {
                        "code": "secret_literal",
                        "message": "Name the password with secret().",
                        "kind": "source",
                        "key": resource["key"],
                        "path": "password",
                    }
                )
        return errors

    def kind_scopes(self, kind: str) -> dict[str, list[str]]:
        if kind not in KIND_SCOPES:
            raise engine_adapter.EngineFailure([{"code": "kind_unsupported", "message": kind}])
        return KIND_SCOPES[kind]

    def natural_key_kinds(self) -> frozenset[str]:
        return NATURAL_KEY_KINDS

    def validate_key(self, kind: str, key: str) -> dict | None:
        if kind in NATURAL_KEY_KINDS or kind in ORGANIZATION_KINDS:
            return None if 0 < len(key) <= 512 else {"code": "invalid_key", "message": "Choose a shorter key."}
        if not key or len(key) > 100 or not all(c.islower() or c.isdigit() or c in "_-" for c in key):
            return {"code": "invalid_key", "message": f"The key {key} is not valid."}
        return None

    def owned_fields(self, kind: str, body: dict) -> frozenset[str]:
        return frozenset(body)

    def ownership_scope(self, kind: str) -> str:
        return "organization" if kind in ORGANIZATION_KINDS else "team"

    def mapped_kinds(self) -> list[str]:
        return sorted(KIND_SCOPES)


class Dispatcher:
    def __init__(self) -> None:
        self.diffs: list[UUID] = []
        self.pushes: list[UUID] = []
        self.push_error: Exception | None = None

    def start_diff(self, *, team_id: int, diff_id: UUID) -> None:
        self.diffs.append(diff_id)

    def start_push(self, *, team_id: int, diff_id: UUID, attempt_id: UUID) -> None:
        if self.push_error is not None:
            raise self.push_error
        self.pushes.append(attempt_id)


def already_started() -> WorkflowAlreadyStartedError:
    return WorkflowAlreadyStartedError("stacks-push-1", "stacks-push")


@contextmanager
def faked_engine() -> Iterator[tuple[FakeEngine, Dispatcher]]:
    engine = FakeEngine()
    dispatcher = Dispatcher()
    fakes: dict[str, Any] = {
        "build_input": engine.build_input,
        "diff": engine.diff,
        "push": engine.push,
        "bindings_in": engine.bindings_in,
        "natural_key_kinds": engine.natural_key_kinds,
        "read_entities": engine.read_entities,
        "validate_description": engine.validate_description,
        "kind_scopes": engine.kind_scopes,
        "validate_key": engine.validate_key,
        "owned_fields": engine.owned_fields,
        "ownership_scope": engine.ownership_scope,
        "mapped_kinds": engine.mapped_kinds,
        "abort_run": lambda: FakeAbortRun,
    }
    with (
        patch.multiple(engine_adapter, **fakes),
        patch("products.stacks.backend.temporal.client.start_diff_workflow", dispatcher.start_diff),
        patch("products.stacks.backend.temporal.client.start_push_workflow", dispatcher.start_push),
    ):
        yield engine, dispatcher
