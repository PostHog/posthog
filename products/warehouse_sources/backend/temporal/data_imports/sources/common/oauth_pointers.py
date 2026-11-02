"""Find the OAuth integration pointer (`*_integration_id`) that a source's ``job_inputs`` use.

A source form declares its OAuth field (`SourceFieldOauthConfig`) at the top level or inside an option
of a select or a switch group. A pointer inside a select is in use only when its option is the
selected one, and a pointer inside a switch group only when the group is on. A pointer under an
option that is not selected is stale: the sync never reads it.

The walk reads only the shape that `serialize_config` writes: a select is a mapping with a
`selection` key, and a switch group is a mapping with an `enabled` key. Older rows can hold other
shapes (flat keys, a select stored as a bare string). The walk raises `OAuthPointerShapeError` for
them and never guesses which pointer is in use.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSwitchGroupConfig,
)

SELECTION_KEY = "selection"
SWITCH_ENABLED_KEY = "enabled"

PointerPath = tuple[str, ...]


@frozen
class OAuthPointer:
    """The pointer that a source uses: where it sits in ``job_inputs`` and the row id it holds."""

    path: PointerPath
    integration_id: int


class OAuthPointerShapeError(ValueError):
    """The inputs hold a select or a switch group with an OAuth field in a shape the walk does not read,
    or a pointer value that is not an integration id. The message never holds a value."""


def declared_oauth_pointer_paths(fields: Iterable[SourceFieldConfig]) -> frozenset[PointerPath]:
    """The path of every OAuth field of the form, under every option. Stale pointers sit at these paths too."""
    return frozenset(path for path, _field in _oauth_fields(fields, ()))


def find_in_use_oauth_pointer(
    fields: Sequence[SourceFieldConfig], job_inputs: Mapping[str, Any]
) -> OAuthPointer | None:
    """The OAuth pointer that the selected options of ``job_inputs`` hold, or None when no pointer is in use.

    Raises `OAuthPointerShapeError` when the inputs cannot tell which pointer is in use.
    """
    found = list(_in_use(fields, job_inputs, (), job_inputs))
    if len(found) > 1:
        raise OAuthPointerShapeError("The inputs hold more than one OAuth pointer in use")
    return found[0] if found else None


def parse_integration_id(value: Any) -> int | None:
    """Read a stored pointer as `str_to_optional_int` does: an int, or a string of digits. None and a
    blank string are no pointer. Raises `OAuthPointerShapeError` for any other value."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise OAuthPointerShapeError("An OAuth pointer must be an integration id")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        if stripped.isascii() and stripped.isdigit():
            return int(stripped)
    raise OAuthPointerShapeError("An OAuth pointer must be an integration id")


def _oauth_fields(
    fields: Iterable[SourceFieldConfig], prefix: PointerPath
) -> Iterator[tuple[PointerPath, SourceFieldOauthConfig]]:
    for field in fields:
        if isinstance(field, SourceFieldOauthConfig):
            yield (*prefix, field.name), field
        elif isinstance(field, SourceFieldSwitchGroupConfig):
            yield from _oauth_fields(field.fields, (*prefix, field.name))
        elif isinstance(field, SourceFieldSelectConfig):
            for option in field.options:
                yield from _oauth_fields(option.fields or [], (*prefix, field.name))


def _in_use(
    fields: Iterable[SourceFieldConfig],
    values: Mapping[str, Any],
    prefix: PointerPath,
    top_level: Mapping[str, Any],
) -> Iterator[OAuthPointer]:
    for field in fields:
        if isinstance(field, SourceFieldOauthConfig):
            integration_id = parse_integration_id(values.get(field.name))
            if integration_id is not None:
                yield OAuthPointer(path=(*prefix, field.name), integration_id=integration_id)
        elif isinstance(field, SourceFieldSelectConfig | SourceFieldSwitchGroupConfig):
            nested_names = {path[-1] for path, _ in _oauth_fields([field], ())}
            if not nested_names:
                continue
            value = values.get(field.name)
            if value is None:
                # An old flat shape keeps the nested pointer next to the select. Do not guess which option it means.
                if any(top_level.get(name) not in (None, "") for name in nested_names):
                    raise OAuthPointerShapeError(f"Field {field.name!r} has an OAuth pointer outside its group")
                continue
            if not isinstance(value, Mapping):
                raise OAuthPointerShapeError(f"Field {field.name!r} is not stored as a mapping")
            yield from _in_use(_selected_fields(field, value), value, (*prefix, field.name), top_level)


def _selected_fields(
    field: SourceFieldSelectConfig | SourceFieldSwitchGroupConfig, value: Mapping[str, Any]
) -> list[SourceFieldConfig]:
    if isinstance(field, SourceFieldSwitchGroupConfig):
        return list(field.fields) if _is_on(field.name, value.get(SWITCH_ENABLED_KEY)) else []
    selection = value.get(SELECTION_KEY)
    for option in field.options:
        if option.value == selection:
            return list(option.fields or [])
    raise OAuthPointerShapeError(f"Field {field.name!r} has no known selected option")


def _is_on(name: str, enabled: Any) -> bool:
    if enabled is None or isinstance(enabled, bool):
        return bool(enabled)
    if isinstance(enabled, str):
        return enabled.lower() in {"true", "yes", "1"}
    raise OAuthPointerShapeError(f"Switch group {name!r} has an unreadable enabled value")
