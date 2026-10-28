import contextlib
from typing import cast

from pydantic import JsonValue
from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.events import EventsGroupSubTable, EventsPersonSubTable, EventsTable
from posthog.hogql.restricted_properties import restricted_property_keys_for_table_type

from posthog.models import Team, User

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.cdp.backend.facade.api import (
    HogFunctionFiltersSerializer,
    action_ids_in_filters,
    filter_property_references,
    require_viewer_access_to_actions,
)
from products.mcp_events.backend.logic.properties import MCPEventPropertyAccess

DERIVED_FILTER_KEYS = frozenset({"bytecode", "bytecode_error", "bytecode_contract", "transpiled"})


def canonicalize_event_filters(raw_filters: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Move action entries into `actions` and write their ids as integer strings.

    The subscription identity hashes the filters, so two spellings of the same action filter must hash the same.
    """
    data = dict(raw_filters)
    events = data.get("events")
    if isinstance(events, list):
        action_entries = [event for event in events if isinstance(event, dict) and event.get("type") == "actions"]
        if action_entries:
            data["events"] = [event for event in events if event not in action_entries]
            actions = data.get("actions")
            data["actions"] = [*(actions if isinstance(actions, list) else []), *action_entries]
    actions = data.get("actions")
    for index, action in enumerate(actions if isinstance(actions, list) else []):
        if isinstance(action, dict) and action.get("type") == "actions":
            action_id = action.get("id")
            if isinstance(action_id, str | int | float):
                with contextlib.suppress(ValueError, OverflowError):
                    normalized_id = int(action_id)
                    if not isinstance(action_id, bool) and (
                        not isinstance(action_id, float) or action_id == normalized_id
                    ):
                        cast(list[JsonValue], actions)[index] = {**action, "id": str(normalized_id)}
    return data


def parse_event_filters(raw_filters: dict[str, JsonValue], *, team: Team, enabled: bool) -> dict[str, JsonValue]:
    """Validate the filters as a destination's and drop the compiled output, which the destination recompiles."""
    if raw_filters.get("source", "events") != "events":
        raise ValidationError({"filters": "MCP subscriptions support captured events. Use source 'events'."})
    if DERIVED_FILTER_KEYS.intersection(raw_filters):
        raise ValidationError({"filters": "Send event filters without compiled bytecode."})
    serializer = HogFunctionFiltersSerializer(
        data=canonicalize_event_filters(raw_filters),
        context={
            "get_team": lambda: team,
            "function_type": "destination",
            "function_will_be_enabled": enabled,
            "strict_event_filters": True,
        },
    )
    serializer.is_valid(raise_exception=True)
    return cast(
        dict[str, JsonValue],
        {key: value for key, value in serializer.validated_data.items() if key not in DERIVED_FILTER_KEYS},
    )


def restricted_event_property_names(*, team: Team, user: User) -> list[str]:
    restrictions = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk)
    if not restrictions:
        return []
    names = MCPEventPropertyAccess.with_group_aliases(
        set(split_restricted_property_names(restrictions).event), team=team
    )
    return sorted(names)


class MCPEventFilterAccessValidator:
    @staticmethod
    def validate_actions(filters: dict[str, JsonValue], *, team: Team, user: User) -> None:
        require_viewer_access_to_actions(
            UserAccessControl(user, team), team=team, action_ids=action_ids_in_filters(filters)
        )

    @staticmethod
    def property_dependencies(filters: dict[str, JsonValue], *, team: Team) -> dict[str, list[str | None]]:
        return filter_property_references(filters, team_id=team.pk)

    @staticmethod
    def validate_snapshot(dependencies: dict[str, list[str | None]], *, team: Team, user: User) -> None:
        restrictions = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk)
        if not restrictions:
            return
        context = HogQLContext(team_id=team.pk, restricted_properties=restrictions)
        table: Table
        for scope, names in dependencies.items():
            if scope == "event":
                table = EventsTable()
            elif scope == "person":
                table = EventsPersonSubTable()
            elif scope in {f"group:{index}" for index in range(5)}:
                table = EventsGroupSubTable(int(scope.removeprefix("group:")))
            else:
                raise PermissionDenied("The filter reads data your account cannot access.")
            keys = restricted_property_keys_for_table_type(ast.TableType(table=table), context)
            if scope == "event":
                keys = MCPEventPropertyAccess.with_group_aliases(keys, team=team)
            for name in names:
                MCPEventPropertyAccess.validate(name, keys)
