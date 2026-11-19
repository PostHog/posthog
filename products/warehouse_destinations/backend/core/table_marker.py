"""The marker a destination stores on the tables it creates.

A destination that has table comments stores the marker there. The marker is a JSON object
with a fixed version key, for example:

    {"posthog_destination": 1, "owner_tag": "a", "committed_staging_key": "run-2"}

- `owner_tag`: the owner tag of the target that created the table.
- `committed_staging_key`: on a final table, the staging key of the REPLACE that last
  committed into it. A replay of that commit finds it and does nothing.
- `require_owned` and `merge`: on a staging table, the settings of `prepare` that a later
  commit needs, so the commit works without the target.

A comment that is not such an object is foreign. `parse` returns None for it and never raises.
"""

import json
import typing

from posthog.dataclasses import frozen

from products.warehouse_destinations.backend.facade.contracts import MergeSpec

_VERSION_KEY = "posthog_destination"
_VERSION = 1


@frozen
class TableMarker:
    owner_tag: str | None = None
    committed_staging_key: str | None = None
    require_owned: bool = False
    merge: MergeSpec | None = None

    def encode(self) -> str:
        payload: dict[str, typing.Any] = {_VERSION_KEY: _VERSION}
        if self.owner_tag is not None:
            payload["owner_tag"] = self.owner_tag
        if self.committed_staging_key is not None:
            payload["committed_staging_key"] = self.committed_staging_key
        if self.require_owned:
            payload["require_owned"] = True
        if self.merge is not None:
            payload["merge"] = {
                "primary_keys": list(self.merge.primary_keys),
                "version_keys": list(self.merge.version_keys),
                "dedupe_source": self.merge.dedupe_source,
            }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def parse(comment: str | None) -> TableMarker | None:
    """Return the marker in `comment`, or None for a missing or foreign comment."""
    if not comment:
        return None
    try:
        payload = json.loads(comment)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get(_VERSION_KEY) != _VERSION:
        return None

    try:
        return TableMarker(
            owner_tag=_optional_str(payload.get("owner_tag")),
            committed_staging_key=_optional_str(payload.get("committed_staging_key")),
            require_owned=payload.get("require_owned") is True,
            merge=_parse_merge(payload.get("merge")),
        )
    except (TypeError, ValueError):
        return None


def is_owned_by(comment: str | None, owner_tag: str) -> bool:
    """Whether the table with `comment` carries exactly `owner_tag`.

    A foreign comment counts only when it equals the tag itself, so a table tagged with the
    plain tag text before markers existed is still recognized.
    """
    marker = parse(comment)
    if marker is None:
        return comment == owner_tag
    return marker.owner_tag == owner_tag


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Expected a string")
    return value


def _parse_merge(value: object) -> MergeSpec | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("Expected an object")
    return MergeSpec(
        primary_keys=tuple(_str_list(value.get("primary_keys"))),
        version_keys=tuple(_str_list(value.get("version_keys", []))),
        dedupe_source=value.get("dedupe_source") is True,
    )


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError("Expected a list of strings")
    return value
