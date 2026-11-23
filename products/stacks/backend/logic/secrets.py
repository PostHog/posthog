"""Secret values a stack's definitions name with `secret('NAME')`. Encrypted at rest, never returned or logged."""

from __future__ import annotations

import re
from typing import Any

from ..db import WRITER_DB
from ..engine_adapter import EngineFailure
from ..facade.contracts import StackServiceError
from ..facade.enums import StackErrorKind
from ..models import Stack, StackSecret
from . import crypto

SECRET_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
MAX_SECRET_BYTES = 64 * 1024


def validate_secret_name(name: str) -> None:
    if not SECRET_NAME.fullmatch(name):
        raise StackServiceError(
            StackErrorKind.INVALID,
            "invalid_secret_name",
            "Use a secret name of letters, digits and underscores that starts with a letter or an underscore, "
            "at most 100 characters.",
        )


def _secrets(stack: Stack):  # noqa: ANN202 — the model's queryset
    # A secret read right after a write must see it, so every read goes to the writer.
    return StackSecret.objects.for_team(stack.team_id, canonical=True).using(WRITER_DB)


def set_secret(stack: Stack, name: str, value: str, user_id: int) -> StackSecret:
    validate_secret_name(name)
    if len(value.encode()) > MAX_SECRET_BYTES:
        raise StackServiceError(StackErrorKind.INVALID, "secret_too_large", "Use a secret value of at most 64 KB.")
    encrypted = crypto.encrypt(value.encode())
    secret, _ = _secrets(stack).update_or_create(
        stack=stack,
        name=name,
        create_defaults={"team_id": stack.team_id, "encrypted_value": encrypted, "updated_by_id": user_id},
        defaults={"encrypted_value": encrypted, "updated_by_id": user_id},
    )
    return secret


def list_secrets(stack: Stack) -> list[StackSecret]:
    return list(_secrets(stack).filter(stack_id=stack.id).only("id", "name", "updated_at", "stack_id").order_by("name"))


def delete_secret(stack: Stack, name: str) -> None:
    deleted, _ = _secrets(stack).filter(stack_id=stack.id, name=name).delete()
    if not deleted:
        raise StackServiceError(
            StackErrorKind.NOT_FOUND, "secret_not_found", f"This stack holds no secret named {name}."
        )


def secret_names(value: Any) -> set[str]:
    """Every name a description references as `{"$secret": "NAME"}`, at any depth."""
    names: set[str] = set()
    stack: list[Any] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if set(item) == {"$secret"} and isinstance(item["$secret"], str):
                names.add(item["$secret"])
                continue
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return names


def missing_secrets(stack: Stack, names: set[str]) -> list[str]:
    if not names:
        return []
    held = set(_secrets(stack).filter(stack_id=stack.id, name__in=sorted(names)).values_list("name", flat=True))
    return sorted(names - held)


def missing_secrets_error(missing: list[str]) -> dict:
    names = ", ".join(missing)
    return {
        "code": "secret_missing",
        "message": f"This stack holds no secret named {names}. Set it with `hog stack secret set {missing[0]}`, "
        "then run diff again.",
    }


def secret_values(stack: Stack, names: set[str]) -> dict[str, str]:
    """The decrypted values of exactly these secrets. Call only in the worker, right before the engine runs."""
    if not names:
        return {}
    rows = _secrets(stack).filter(stack_id=stack.id, name__in=sorted(names))
    values = {row.name: crypto.decrypt(row.encrypted_value).decode() for row in rows}
    if missing := sorted(names - set(values)):
        # A push names secrets its diff found. One removed since must stop it, never run with a gap.
        raise EngineFailure([missing_secrets_error(missing)])
    return values
