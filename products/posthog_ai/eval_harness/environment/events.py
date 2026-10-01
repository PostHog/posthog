from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import cast
from uuid import uuid5

from pydantic import JsonValue

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Team
from posthog.models.event.new_events_schema import use_new_events_schema
from posthog.models.event.sql import BULK_INSERT_EVENT_SQL, EVENTS_DATA_TABLE, EVENTS_JSON_DATA_TABLE
from posthog.models.event.util import _json_dumps_for_clickhouse
from posthog.models.group.sql import GROUPS_TABLE
from posthog.models.person.sql import PERSONS_TABLE

from products.demo.backend.facade.api import infer_taxonomy_for_team
from products.posthog_ai.eval_harness.environment.dataset import EnvironmentDataset, validate_json_numbers
from products.posthog_ai.eval_harness.environment.guard import assert_local_databases
from products.posthog_ai.eval_harness.environment.transform import EnvironmentTransform


class RestoredEventSummary:
    def __init__(self, timestamp: datetime) -> None:
        self.count = 1
        self.minimum = timestamp
        self.maximum = timestamp

    def observe(self, timestamp: datetime) -> None:
        self.count += 1
        self.minimum = min(self.minimum, timestamp)
        self.maximum = max(self.maximum, timestamp)

    def as_json(self) -> dict[str, JsonValue]:
        return {
            "count": self.count,
            "min_timestamp": self.minimum.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "max_timestamp": self.maximum.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }


class EnvironmentEvents:
    @staticmethod
    def preflight() -> None:
        identity = assert_local_databases()
        required = {EVENTS_DATA_TABLE(), "events", PERSONS_TABLE, GROUPS_TABLE}
        native = use_new_events_schema()
        if native:
            required.add(EVENTS_JSON_DATA_TABLE)
        with tags_context(
            product=Product.MAX_AI,
            feature=Feature.MANAGEMENT_COMMAND,
            kind="management_command",
            query_type="eval_environment",
        ):
            rows = sync_execute(
                "SELECT name FROM system.tables WHERE database = %(database)s AND name IN %(tables)s",
                {"database": identity["clickhouse_database"], "tables": tuple(sorted(required))},
            )
            if {row[0] for row in rows} != required:
                raise RuntimeError("ClickHouse event tables are not ready; complete local migrations before importing.")
            if native:
                functions = sync_execute(
                    "SELECT name FROM system.functions WHERE name IN %(functions)s",
                    {"functions": ("JSONCleanPostHogEventProperties", "JSONCleanPostHogTemporaryProperties")},
                )
                if len(functions) != 2:
                    raise RuntimeError("ClickHouse native JSON cleanup functions are not ready.")

    @staticmethod
    def summaries(dataset: EnvironmentDataset, transformer: EnvironmentTransform) -> dict[str, RestoredEventSummary]:
        summaries: dict[str, RestoredEventSummary] = {}
        for event in dataset.events():
            timestamp = event.timestamp + transformer.delta
            if summary := summaries.get(event.event):
                summary.observe(timestamp)
            else:
                summaries[event.event] = RestoredEventSummary(timestamp)
        return summaries

    @staticmethod
    def validate(team_id: int, summaries: dict[str, RestoredEventSummary]) -> dict[str, JsonValue]:
        assert_local_databases()
        expected: dict[str, JsonValue] = {event: summary.as_json() for event, summary in summaries.items()}
        with tags_context(
            product=Product.MAX_AI,
            feature=Feature.MANAGEMENT_COMMAND,
            kind="management_command",
            query_type="eval_environment",
            team_id=team_id,
        ):
            result = execute_hogql_query(
                "SELECT event, count(), "
                "formatDateTime(min(timestamp), '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC'), "
                "formatDateTime(max(timestamp), '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') "
                "FROM events GROUP BY event ORDER BY event LIMIT {event_limit}",
                team=Team.objects.get(id=team_id),
                placeholders={"event_limit": ast.Constant(value=len(expected) + 1)},
            )
        actual = {
            row[0]: {"count": row[1], "min_timestamp": row[2], "max_timestamp": row[3]} for row in result.results or []
        }
        if actual != expected:
            raise ValueError("Restored event counts or timestamp bounds differ from the prepared environment.")
        return {"matched": True, "query_performed": True, "by_event": expected}

    @classmethod
    def restore(
        cls, dataset: EnvironmentDataset, transformer: EnvironmentTransform, team_id: int
    ) -> dict[str, JsonValue]:
        assert_local_databases()
        native = use_new_events_schema(team_id)
        batch: list[dict[str, object]] = []
        summaries: dict[str, RestoredEventSummary] = {}
        now = datetime.now(UTC)
        for event in dataset.events():
            properties = cast(dict[str, JsonValue], transformer.value(event.properties))
            validate_json_numbers(properties)
            timestamp = event.timestamp + transformer.delta
            row: dict[str, object] = {
                "uuid": str(event.uuid),
                "event": event.event,
                "properties": json.dumps(properties, allow_nan=False),
                "timestamp": timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
                "team_id": team_id,
                "distinct_id": event.distinct_id,
                "elements_chain": "",
                "person_id": event.person_id or uuid5(transformer.namespace, event.distinct_id),
                "person_properties": "{}",
                "person_created_at": now,
                **{f"group{i}_properties": "{}" for i in range(5)},
                **{f"group{i}_created_at": now for i in range(5)},
                "person_mode": "full",
                "created_at": (event.created_at + transformer.delta).astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
                "_timestamp": now,
                "_offset": 0,
            }
            batch.append(row)
            if summary := summaries.get(event.event):
                summary.observe(timestamp)
            else:
                summaries[event.event] = RestoredEventSummary(timestamp)
            if len(batch) >= 5_000:
                cls._insert(batch, team_id, native)
                batch = []
        if batch:
            cls._insert(batch, team_id, native)
        if summaries:
            with tags_context(
                product=Product.MAX_AI,
                feature=Feature.MANAGEMENT_COMMAND,
                kind="management_command",
                query_type="eval_environment",
                team_id=team_id,
            ):
                infer_taxonomy_for_team(team_id)
        return cls.validate(team_id, summaries)

    @staticmethod
    def _insert(rows: list[dict[str, object]], team_id: int, native: bool) -> None:
        assert_local_databases()
        columns = tuple(rows[0])
        values = ", ".join(
            "(" + ", ".join(f"%({column}_{index})s" for column in columns) + ")" for index in range(len(rows))
        )
        params = {f"{column}_{index}": row[column] for index, row in enumerate(rows) for column in columns}
        with tags_context(
            product=Product.MAX_AI,
            feature=Feature.MANAGEMENT_COMMAND,
            kind="management_command",
            query_type="eval_environment",
            team_id=team_id,
        ):
            # Taxonomy inference still reads the legacy table even when HogQL uses native JSON.
            sync_execute(BULK_INSERT_EVENT_SQL(values=values), params)
            if native:
                native_params = dict(params)
                for index, row in enumerate(rows):
                    native_params[f"properties_{index}"] = _json_dumps_for_clickhouse(
                        json.loads(str(row["properties"]))
                    )
                sync_execute(BULK_INSERT_EVENT_SQL(table_name=EVENTS_JSON_DATA_TABLE, values=values), native_params)
