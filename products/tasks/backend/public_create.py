import json
import hashlib
from collections.abc import Mapping
from typing import Any

from rest_framework.fields import BooleanField

from posthog.dataclasses import frozen

from products.tasks.backend.facade.profiles import Repository, TaskRunOptions

PUBLIC_CREATE_FIELDS = ("options", "source", "idempotency_key")


@frozen
class IdempotentRequest:
    key: str
    fingerprint: str


def uses_public_create(validated_data: Mapping[str, Any]) -> bool:
    return any(validated_data.get(field) for field in PUBLIC_CREATE_FIELDS)


def options_from_request(data: Mapping[str, Any]) -> TaskRunOptions:
    return TaskRunOptions(
        runtime=data.get("runtime"),
        adapter=data.get("adapter"),
        model=data.get("model"),
        reasoning_effort=data.get("reasoning_effort"),
        repositories=tuple(
            Repository(name=repository["name"], initial_branch=repository.get("initial_branch"))
            for repository in data.get("repositories", ())
        ),
        output_schema=data.get("output_schema"),
        permission_mode=data.get("permission_mode"),
        auto_publish=data.get("auto_publish"),
    )


def create_fields_from_options(options: TaskRunOptions, *, repositories_given: bool = False) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if options.runtime is not None:
        fields["runtime"] = options.runtime
    if options.adapter is not None:
        fields["runtime_adapter"] = options.adapter
    if options.model is not None:
        fields["model"] = options.model
    if options.reasoning_effort is not None:
        fields["reasoning_effort"] = options.reasoning_effort
    if options.repositories:
        fields["repositories"] = [repository.name for repository in options.repositories]
        if options.repositories[0].initial_branch:
            fields["branch"] = options.repositories[0].initial_branch
    elif repositories_given:
        fields["repositories"] = []
    if options.output_schema is not None:
        fields["json_schema"] = options.output_schema
    if options.permission_mode is not None:
        fields["initial_permission_mode"] = options.permission_mode
    if options.auto_publish is not None:
        fields["auto_publish"] = options.auto_publish
    return fields


def request_fingerprint(data: Mapping[str, Any]) -> str:
    body = {key: value for key, value in data.items() if key != "idempotency_key"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def public_idempotency_key(user_id: int | None, key: str) -> str:
    return f"api:{user_id}:{key}"


def idempotent_request(user_id: int | None, data: Any) -> IdempotentRequest | None:
    if not isinstance(data, Mapping) or "profile" not in data:
        return None
    key = data.get("idempotency_key")
    if not isinstance(key, str) or not key.strip():
        return None
    return IdempotentRequest(key=public_idempotency_key(user_id, key.strip()), fingerprint=request_fingerprint(data))


def asks_for_run(data: Mapping[str, Any]) -> bool:
    value = data.get("start_run")
    return isinstance(value, bool | int | str) and value in BooleanField.TRUE_VALUES
