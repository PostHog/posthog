from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import JsonValue

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.models import Team, User
from posthog.models.event.new_events_schema import use_new_events_schema
from posthog.models.event.sql import BULK_INSERT_EVENT_SQL, EVENTS_JSON_DATA_TABLE
from posthog.models.event.util import _json_dumps_for_clickhouse
from posthog.models.person.sql import BULK_INSERT_PERSON_DISTINCT_ID2, INSERT_PERSON_BULK_SQL

from products.demo.backend.facade.api import infer_taxonomy_for_team
from products.error_tracking.backend.facade.testing import (
    create_issue,
    create_issue_fingerprint,
    sync_issue_to_clickhouse,
)
from products.posthog_ai.evals.error_tracking.seeders import _build_exception_properties
from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.warehouse_sources.backend.facade.api import all_queryable_table_names, soft_delete_tables

from .first_report_fixture import (
    BASELINE_VERSION,
    CURRENT_VERSION,
    UPLOAD_ERROR,
    UPLOAD_FINGERPRINT,
    UploadEvent,
    upload_events,
)


def insert_events(team: Team, events: list[UploadEvent]) -> None:
    native_schema = use_new_events_schema(team.pk)
    columns = [
        "uuid",
        "event",
        "properties",
        "timestamp",
        "team_id",
        "distinct_id",
        "elements_chain",
        "person_id",
        "person_properties",
        "person_created_at",
        *[f"group{i}_properties" for i in range(5)],
        *[f"group{i}_created_at" for i in range(5)],
        "person_mode",
        "created_at",
    ]
    people = {event.distinct_id: event for event in events if event.event == "signed_up"}
    person_values: list[str] = []
    identity_values: list[str] = []
    params: dict[str, object] = {"team": team.id}
    for index, event in enumerate(people.values()):
        params.update(
            {
                f"id{index}": event.person_id,
                f"distinct{index}": event.distinct_id,
                f"time{index}": event.timestamp,
                f"props{index}": "{}",
            }
        )
        person_values.append(
            f"(%(id{index})s, %(time{index})s, %(team)s, %(props{index})s, 1, now(), 0, 0, 1, %(time{index})s)"
        )
        identity_values.append(f"(%(distinct{index})s, %(id{index})s, %(team)s, 0, 1, now(), 0, 0)")
    sync_execute(INSERT_PERSON_BULK_SQL + ",".join(person_values), params, workload=Workload.OFFLINE, team_id=team.id)
    sync_execute(
        BULK_INSERT_PERSON_DISTINCT_ID2 + ",".join(identity_values), params, workload=Workload.OFFLINE, team_id=team.id
    )
    for offset in range(0, len(events), 250):
        rows: list[str] = []
        params = {}
        for index, event in enumerate(events[offset : offset + 250]):
            row: dict[str, object] = {
                "uuid": str(uuid4()),
                "event": event.event,
                "properties": _json_dumps_for_clickhouse(event.properties)
                if native_schema
                else json.dumps(event.properties),
                "timestamp": event.timestamp,
                "team_id": team.id,
                "distinct_id": event.distinct_id,
                "elements_chain": "",
                "person_id": event.person_id,
                "person_properties": "{}",
                "person_created_at": people[event.distinct_id].timestamp,
                "person_mode": "full",
                "created_at": event.timestamp,
                **{f"group{i}_properties": "{}" for i in range(5)},
                **{f"group{i}_created_at": "1970-01-01 00:00:00" for i in range(5)},
            }
            params.update({f"{column}_{index}": row[column] for column in columns})
            rows.append("(" + ",".join(f"%({column}_{index})s" for column in columns) + ",now(),0)")
        sync_execute(
            BULK_INSERT_EVENT_SQL(EVENTS_JSON_DATA_TABLE if native_schema else None, values=",".join(rows)),
            params,
            workload=Workload.OFFLINE,
            team_id=team.id,
        )


def seed_upload_case(
    context: CustomPromptSandboxContext, scenario: Literal["regression", "control", "sparse"]
) -> dict[str, JsonValue]:
    team = Team.objects.select_related("organization").get(id=context.team_id)
    # Harness labels name the scenario; the scout must discover it from project data.
    team.organization.name = "Hedgebox"
    team.organization.save(update_fields=["name"])
    User.objects.filter(id=context.user_id).update(email=f"analyst-{context.user_id}@hedgebox.example")
    anchor = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    events = upload_events(anchor, scenario=scenario)
    # The copied warehouse CSVs are immutable snapshots and would contradict this case's new event history.
    soft_delete_tables(team.id, list(all_queryable_table_names(team.id).values()))
    issue_id: str | None = None
    if scenario == "regression":
        issue_uuid = create_issue(team_id=team.id, name="File upload request failure")
        create_issue_fingerprint(
            team_id=team.id,
            issue_id=issue_uuid,
            fingerprint=UPLOAD_FINGERPRINT,
            first_seen=min(event.timestamp for event in events if event.event == "$exception"),
        )
        sync_issue_to_clickhouse(team_id=team.id, issue_id=issue_uuid)
        issue_id = str(issue_uuid)
        for event in events:
            if event.event == "$exception":
                event.properties.update(
                    _build_exception_properties(
                        {
                            "type": "UploadError",
                            "value": UPLOAD_ERROR,
                            "url": "https://hedgebox.net/files/",
                            "source": "https://hedgebox.net/static/upload.js",
                            "function": "prepareUpload",
                            "fingerprint": UPLOAD_FINGERPRINT,
                        },
                        issue_id,
                        str(event.properties["$session_id"]),
                    )
                )
    insert_events(team, events)
    team.ingested_event = True
    team.completed_snippet_onboarding = True
    team.has_completed_onboarding_for = {**(team.has_completed_onboarding_for or {}), "product_analytics": True}
    if scenario != "sparse":
        team.has_completed_onboarding_for["error_tracking"] = True
    team.save(update_fields=["ingested_event", "completed_snippet_onboarding", "has_completed_onboarding_for"])
    infer_taxonomy_for_team(team.id)
    result = execute_hogql_query(
        """SELECT properties.$browser AS browser, properties.app_version AS version,
                  uniqExactIf(distinct_id, event = 'signed_up') AS signups,
                  uniqExactIf(distinct_id, event = 'uploaded_file') AS uploads,
                  uniqExactIf(distinct_id, event = '$exception') AS affected_users
           FROM events WHERE timestamp >= now() - INTERVAL 16 DAY AND timestamp < now()
           AND properties.app_version IN ({baseline}, {current})
           GROUP BY browser, version ORDER BY browser, version""",
        team=team,
        workload=Workload.OFFLINE,
        placeholders={"baseline": ast.Constant(value=BASELINE_VERSION), "current": ast.Constant(value=CURRENT_VERSION)},
    )
    oracle: list[JsonValue] = [
        {"browser": row[0], "version": row[1], "signups": row[2], "uploads": row[3], "affected_users": row[4]}
        for row in result.results
    ]
    expected_counts = Counter(
        (str(event.properties["$browser"]), str(event.properties["app_version"]), event.event)
        for event in events
        if event.event in ("signed_up", "uploaded_file", "$exception")
    )
    actual_counts = {
        (str(row[0]), str(row[1]), event): int(row[column])
        for row in result.results
        for event, column in (("signed_up", 2), ("uploaded_file", 3), ("$exception", 4))
        if row[column]
    }
    if actual_counts != expected_counts:
        raise RuntimeError("The fixture's signup, upload, and exception cohorts are not queryable")
    return {"scenario": scenario, "anchor": anchor.isoformat(), "issue_id": issue_id, "cohorts": oracle}


def seed_upload_regression(context: CustomPromptSandboxContext) -> dict[str, JsonValue]:
    return seed_upload_case(context, "regression")


def seed_upload_control(context: CustomPromptSandboxContext) -> dict[str, JsonValue]:
    return seed_upload_case(context, "control")


def seed_sparse_project(context: CustomPromptSandboxContext) -> dict[str, JsonValue]:
    return seed_upload_case(context, "sparse")
