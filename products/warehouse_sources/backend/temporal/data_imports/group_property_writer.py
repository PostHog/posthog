"""Direct write of warehouse group properties, without a `$groupidentify` event.

The writer does the three things ingestion does for a `$groupidentify`: it merges the properties
onto the group in personhog, it writes the group row to ClickHouse, and it sets the type of each
property definition. It does not write an event, so a sync does not count as activity and does not
bill.
"""

import re
import time
from collections.abc import Callable
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal, cast

from django.db.models import BigIntegerField
from django.db.models.functions import Coalesce

from posthog.constants import GROUP_TYPES_LIMIT
from posthog.dataclasses import frozen
from posthog.models import PropertyDefinition
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group.util import create_group, get_group_by_key, raw_create_group_ch, save_group

from products.warehouse_sources.backend.facade.person_property_provenance import MAX_PROPERTY_NAME_BYTES

GroupWriteOutcome = Literal["created", "updated", "unchanged"]

_STRING = "String"
_NUMERIC = "Numeric"
_BOOLEAN = "Boolean"
_DATETIME = "DateTime"

# The type rules below mirror `detect_property_type` in rust/property-defs-rs/src/types.rs. That
# service sets the type of a group property definition from a `$groupidentify` event, and a direct
# write sends no event, so a different rule here gives a synced property a different type.
_ALWAYS_STRING_PREFIXES = ("utm_", "$initial_utm_", "$feature/", "$survey_response")
_ALWAYS_STRING_NAMES = frozenset({"$feature_flag_response", "$mcp_protocol_version"})
_DATETIME_NAME_KEYWORDS = ("time", "date", "_at", "-at", "createdat", "updatedat")
_DATETIME_PREFIX_REGEX = re.compile(
    r"^(([0-9]{4}[/-][0-2][0-9][/-][0-3][0-9])|([0-2][0-9][/-][0-3][0-9][/-][0-9]{4}))"
    r"([ T][0-2][0-9]:[0-6][0-9]:[0-6][0-9].*)?$"
)
_RFC3339_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")
_SIX_MONTHS_SECONDS = 15768000

# Bounds the per-process set of definitions that already have a type.
_MAX_TYPED_DEFINITIONS_CACHED = 50_000


def _is_likely_date_string(value: str) -> bool:
    if _DATETIME_PREFIX_REGEX.match(value):
        return True
    if _RFC3339_REGEX.match(value):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
            return True
        except ValueError:
            return False
    try:
        parsedate_to_datetime(value)
        return True
    except (TypeError, ValueError):
        return False


def detect_property_type(name: str, value: object, *, now: Callable[[], float] = time.time) -> str | None:
    """The definition type that ingestion gives this property, or None when the value has no type."""
    key = name.lower()
    if key.startswith(_ALWAYS_STRING_PREFIXES) or key in _ALWAYS_STRING_NAMES:
        return _STRING
    if isinstance(value, bool):
        return _BOOLEAN
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed in ("true", "false", "TRUE", "FALSE"):
            return _BOOLEAN
        return _DATETIME if _is_likely_date_string(trimmed) else _STRING
    if isinstance(value, int):
        is_recent_timestamp = value >= now() - _SIX_MONTHS_SECONDS
        if is_recent_timestamp and any(keyword in key for keyword in _DATETIME_NAME_KEYWORDS):
            return _DATETIME
        return _NUMERIC
    if isinstance(value, float):
        return _NUMERIC
    return None


@frozen
class GroupPropertyUpdate:
    team_id: int
    project_id: int
    group_type_index: GroupTypeIndex
    group_key: str
    properties: dict[str, Any]


def parse_group_update(payload: dict[str, Any]) -> GroupPropertyUpdate | None:
    """Map a group topic message to a direct write. Return None when the message does not carry the
    ids that a direct write needs, which is the case for a message produced before `project_id`
    was added to it."""
    team_id = payload.get("team_id")
    project_id = payload.get("project_id")
    group_type_index = payload.get("group_type_index")
    group_key = payload.get("group_key")
    properties = payload.get("properties")
    ids = (team_id, project_id, group_type_index)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in ids):
        return None
    if not 0 <= cast(int, group_type_index) < GROUP_TYPES_LIMIT:
        return None
    if group_key is None or group_key == "" or not isinstance(properties, dict) or not properties:
        return None
    return GroupPropertyUpdate(
        team_id=cast(int, team_id),
        project_id=cast(int, project_id),
        group_type_index=cast(GroupTypeIndex, group_type_index),
        group_key=str(group_key),
        properties=properties,
    )


class GroupPropertyWriter:
    def __init__(self) -> None:
        self._typed_definitions: set[tuple[int, int, str]] = set()

    def write(self, update: GroupPropertyUpdate) -> GroupWriteOutcome:
        outcome = self._write_group(update)
        self._set_definition_types(update)
        return outcome

    def _write_group(self, update: GroupPropertyUpdate) -> GroupWriteOutcome:
        group = get_group_by_key(update.team_id, update.group_type_index, update.group_key)
        if group is None:
            # The producer sends an update only for a group that exists, so the group was deleted
            # after the message was produced. Ingestion creates the group in that case.
            create_group(update.team_id, update.group_type_index, update.group_key, dict(update.properties))
            return "created"
        current = group.group_properties or {}
        merged = {**current, **update.properties}
        if merged == current:
            return "unchanged"
        # UpdateGroup replaces the full properties blob and has no version condition. A
        # `$groupidentify` that ingestion applies between the read above and this write loses its
        # properties. The groups API has the same window.
        group.group_properties = merged
        save_group(group, operation="warehouse_group_property_sync")
        raw_create_group_ch(update.team_id, update.group_type_index, update.group_key, merged, group.created_at)
        return "updated"

    def _set_definition_types(self, update: GroupPropertyUpdate) -> None:
        detected: dict[str, str] = {}
        for name, value in update.properties.items():
            if len(name.encode()) > MAX_PROPERTY_NAME_BYTES:
                continue
            canonical_name = name.replace("\x00", "�")
            if (update.project_id, update.group_type_index, canonical_name) in self._typed_definitions:
                continue
            property_type = detect_property_type(name, value)
            if property_type is not None:
                detected[canonical_name] = property_type
        if not detected:
            return

        query = PropertyDefinition.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=BigIntegerField())
        ).filter(
            effective_project_id=update.project_id,
            type=PropertyDefinition.Type.GROUP,
            group_type_index=update.group_type_index,
        )
        existing = set(query.filter(name__in=list(detected)).values_list("name", flat=True))
        missing = [name for name in detected if name not in existing]
        if missing:
            PropertyDefinition.objects.bulk_create(
                [
                    PropertyDefinition(
                        team_id=update.team_id,
                        project_id=update.project_id,
                        name=name,
                        type=PropertyDefinition.Type.GROUP,
                        group_type_index=update.group_type_index,
                        property_type=detected[name],
                        is_numerical=detected[name] == _NUMERIC,
                    )
                    for name in missing
                ],
                ignore_conflicts=True,
            )
        # Ingestion sets a type only on a definition that has none, so a type that a user or an
        # earlier value set is never changed.
        for property_type in set(detected.values()):
            names = [name for name, detected_type in detected.items() if detected_type == property_type]
            query.filter(name__in=names, property_type__isnull=True).update(
                property_type=property_type, is_numerical=property_type == _NUMERIC
            )

        if len(self._typed_definitions) + len(detected) > _MAX_TYPED_DEFINITIONS_CACHED:
            self._typed_definitions.clear()
        self._typed_definitions.update((update.project_id, update.group_type_index, name) for name in detected)
