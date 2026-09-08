import uuid
from collections.abc import Iterator
from typing import Any

from posthog.models.entity_dependencies.registry import (
    DependencyResolver,
    DependencySource,
    register_resolver,
    register_source,
)
from posthog.models.entity_dependencies.types import EntityRef, EntityRefStatus, Reference

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

# Batch and schedule triggers resolve their audience offline from precalculated cohort membership,
# which is why only these two get the audience role: the impact rules for a cohort change differ
# from a cohort used as an event-time filter.
AUDIENCE_TRIGGER_TYPES = frozenset({"batch", "schedule"})


class HogFlowDependencySource(DependencySource[HogFlow]):
    entity_type = "hog_flow"
    model = HogFlow

    def extract_references(self, instance: HogFlow) -> list[Reference]:
        if instance.status == HogFlow.State.ARCHIVED:
            return []
        live = {"trigger": instance.trigger, "actions": instance.actions, "conversion": instance.conversion}
        references = list(_cohort_references(live, role_prefix="", path_prefix=""))
        if isinstance(instance.draft, dict):
            references.extend(_cohort_references(instance.draft, role_prefix="draft:", path_prefix="draft."))
        return references


def _cohort_references(content: dict[str, Any], *, role_prefix: str, path_prefix: str) -> Iterator[Reference]:
    """Walk every filter slot of a workflow's content (live or draft) for cohort property filters.

    Only known filter slots are visited, so free-form action inputs and the percentage buckets of
    `random_cohort_branch` (which are not cohorts) can never produce a reference.
    """
    trigger_config = _as_dict(_as_dict(content.get("trigger")).get("config"))
    trigger_role = "trigger_audience" if trigger_config.get("type") in AUDIENCE_TRIGGER_TYPES else "trigger_filter"
    yield from _references_in(
        trigger_config.get("filters"), role=role_prefix + trigger_role, path=path_prefix + "trigger.config.filters"
    )

    for action in _as_list(content.get("actions")):
        if not isinstance(action, dict):
            continue
        config = _as_dict(action.get("config"))
        action_path = f"{path_prefix}actions[{action.get('id')}].config"
        if action.get("type") == "conditional_branch":
            for index, condition in enumerate(_as_list(config.get("conditions"))):
                yield from _references_in(
                    _as_dict(condition).get("filters"),
                    role=role_prefix + "branch_condition",
                    path=f"{action_path}.conditions[{index}].filters",
                )
        elif action.get("type") == "wait_until_condition":
            yield from _references_in(
                _as_dict(config.get("condition")).get("filters"),
                role=role_prefix + "wait_condition",
                path=f"{action_path}.condition.filters",
            )
            for index, event in enumerate(_as_list(config.get("events"))):
                yield from _references_in(
                    _as_dict(event).get("filters"),
                    role=role_prefix + "wait_condition",
                    path=f"{action_path}.events[{index}].filters",
                )

    conversion = _as_dict(content.get("conversion"))
    yield from _references_in(
        conversion.get("filters"), role=role_prefix + "conversion", path=path_prefix + "conversion.filters"
    )
    for index, event in enumerate(_as_list(conversion.get("events"))):
        yield from _references_in(
            _as_dict(event).get("filters"),
            role=role_prefix + "conversion",
            path=f"{path_prefix}conversion.events[{index}].filters",
        )


def _references_in(node: Any, *, role: str, path: str) -> Iterator[Reference]:
    # A cohort property filter is `{key: "id", type: "cohort", value: <id>, operator: "in"}`. Filters
    # nest (property groups, per-event properties), so walk every dict and list below the slot.
    if isinstance(node, dict):
        if node.get("type") == "cohort" and node.get("value") is not None:
            values = node["value"] if isinstance(node["value"], list) else [node["value"]]
            for value in values:
                cohort_id = _cohort_id(value)
                if cohort_id is not None:
                    yield Reference(target_type="cohort", target_id=cohort_id, role=role, path=path)
            return
        for key, child in node.items():
            yield from _references_in(child, role=role, path=f"{path}.{key}")
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _references_in(child, role=role, path=f"{path}[{index}]")


def _cohort_id(value: Any) -> str | None:
    # Cohort ids arrive as ints or numeric strings depending on the client; anything else cannot
    # name a cohort and is skipped rather than recorded as a bogus target.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.isdigit():
        return str(int(value))
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


class HogFlowDependencyResolver(DependencyResolver):
    entity_type = "hog_flow"

    def resolve(self, team_id: int, ids: list[str]) -> dict[str, EntityRef]:
        valid_ids = [entity_id for entity_id in ids if _is_uuid(entity_id)]
        if not valid_ids:
            return {}
        refs: dict[str, EntityRef] = {}
        for flow in HogFlow.objects.filter(team_id=team_id, id__in=valid_ids).only("id", "name", "status"):
            refs[str(flow.id)] = EntityRef(
                type="hog_flow",
                id=str(flow.id),
                name=flow.name or "",
                url=f"/workflows/{flow.id}/workflow",
                status=EntityRefStatus.ARCHIVED if flow.status == HogFlow.State.ARCHIVED else EntityRefStatus.ACTIVE,
            )
        return refs


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


register_source(HogFlowDependencySource())
register_resolver(HogFlowDependencyResolver())
