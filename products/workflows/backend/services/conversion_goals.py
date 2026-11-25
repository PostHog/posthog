import json
import hashlib
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from products.workflows.backend.facade.contracts import ConversionGoalBackfill
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_conversion_goal import HogFlowConversionGoal
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision


def pin_conversion_goal(conversion: Any) -> Optional[dict]:
    """Builds the goal a run saves when it starts under this conversion: the same shape Node's `pinConversionGoal`
    (nodejs/src/cdp/services/hogflows/conversion-watcher.ts) writes to `conversion_watchers.goal`."""
    if not isinstance(conversion, dict):
        return None
    filters = conversion.get("filters")
    bytecode = conversion.get("bytecode")
    properties = bytecode if isinstance(filters, list) and filters and isinstance(bytecode, list) else None
    events = []
    for event_config in conversion.get("events") or []:
        event_filters = event_config.get("filters") if isinstance(event_config, dict) else None
        if not isinstance(event_filters, dict):
            continue
        # An entry that targets neither events nor actions compiles to always-true bytecode, so runs drop it too.
        if not (event_filters.get("events") or event_filters.get("actions")):
            continue
        event_bytecode = event_filters.get("bytecode")
        if isinstance(event_bytecode, list) and event_bytecode:
            events.append(event_bytecode)
    goal: dict[str, Any] = {}
    if properties:
        goal["properties"] = properties
    if events:
        goal["events"] = events
    return goal or None


def goal_event_names(conversion: Any) -> Optional[list[str]]:
    """The event names a pinned goal of this conversion can match, or None when it can match any. Mirrors
    `rejectsEventName` in nodejs/src/cdp/utils/hog-function-filtering.ts."""
    if not isinstance(conversion, dict) or pin_conversion_goal(conversion) is None:
        return None
    if isinstance(conversion.get("filters"), list) and conversion["filters"]:
        return None
    names: set[str] = set()
    for event_config in conversion.get("events") or []:
        event_filters = event_config.get("filters") if isinstance(event_config, dict) else None
        if not isinstance(event_filters, dict) or not (event_filters.get("events") or event_filters.get("actions")):
            continue
        # A run drops entries without bytecode when it saves its goal, so they cannot match any event.
        bytecode = event_filters.get("bytecode")
        if not isinstance(bytecode, list) or not bytecode:
            continue
        if event_filters.get("actions") or not isinstance(event_filters.get("events"), list):
            return None
        for event_filter in event_filters["events"]:
            if not isinstance(event_filter, dict) or event_filter.get("type") != "events":
                return None
            if event_filter.get("id") is None:
                return None
            names.add(str(event_filter["id"]))
    return sorted(names)


def goal_hash(goal: dict) -> str:
    return hashlib.sha256(json.dumps(goal, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def record_conversion_goals(
    team_id: int, hog_flow_id: UUID, conversions: Iterable[Any], *, live_at: Optional[datetime] = None
) -> int:
    """Store the goals of these conversions for the workflow as live now, moving the time forward on goals it
    already has. With an explicit `live_at`, only goals it lacks are stored, so an older time never replaces a
    newer one. Returns how many goals it tried to store."""
    goals: dict[str, tuple[dict, Optional[list[str]]]] = {}
    for conversion in conversions:
        goal = pin_conversion_goal(conversion)
        if goal is not None:
            goals[goal_hash(goal)] = (goal, goal_event_names(conversion))
    if not goals:
        return 0
    rows = [
        HogFlowConversionGoal(
            team_id=team_id,
            hog_flow_id=hog_flow_id,
            goal_hash=key,
            goal=goal,
            event_names=event_names,
            last_live_at=live_at or timezone.now(),
        )
        for key, (goal, event_names) in goals.items()
    ]
    if live_at is None:
        HogFlowConversionGoal.objects.unscoped().bulk_create(
            rows, update_conflicts=True, unique_fields=["hog_flow", "goal_hash"], update_fields=["last_live_at"]
        )
    else:
        HogFlowConversionGoal.objects.unscoped().bulk_create(rows, ignore_conflicts=True)
    return len(goals)


def backfill_conversion_goals(*, team_id: Optional[int], batch_size: int, live_run: bool) -> ConversionGoalBackfill:
    """Record the goals of every workflow's live conversion and of its revisions, for runs that started before
    saves recorded goals. Running it again changes nothing. Without `live_run` it only counts."""
    flows = HogFlow.objects.filter(conversion__isnull=False)
    # Only the conversion key, so Postgres sends the goal rather than each whole snapshot.
    revisions = HogFlowRevision.objects.unscoped().filter(content__conversion__isnull=False)
    if team_id is not None:
        flows = flows.filter(team_id=team_id)
        revisions = revisions.filter(team_id=team_id)

    # A goal stopped being live no later than its workflow's last change, unless it is the current goal of an
    # active workflow.
    now = timezone.now()
    read = {"workflows": 0, "revisions": 0}
    goals = 0
    for source, queryset, flow_field, conversion_field, updated_field, status_field in (
        ("workflows", flows, "pk", "conversion", "updated_at", "status"),
        ("revisions", revisions, "hog_flow_id", "content__conversion", "hog_flow__updated_at", None),
    ):
        last_pk = None
        while True:
            page = queryset.order_by("pk")
            if last_pk is not None:
                page = page.filter(pk__gt=last_pk)
            fields = ["pk", "team_id", flow_field, conversion_field, updated_field]
            batch = list(page.values_list(*fields, status_field or updated_field)[:batch_size])
            if not batch:
                break
            last_pk = batch[-1][0]
            for _, row_team_id, hog_flow_id, conversion, updated_at, status in batch:
                read[source] += 1
                live_at = now if status_field and status == HogFlow.State.ACTIVE else updated_at
                if live_run:
                    with transaction.atomic():
                        # Lock the workflow first, as a save does, so the two cannot deadlock on each other.
                        if not HogFlow.objects.select_for_update().filter(pk=hog_flow_id, team_id=row_team_id).exists():
                            continue
                        goals += record_conversion_goals(row_team_id, hog_flow_id, [conversion], live_at=live_at)
                elif pin_conversion_goal(conversion) is not None:
                    goals += 1
    return ConversionGoalBackfill(workflows_read=read["workflows"], revisions_read=read["revisions"], goals_found=goals)
