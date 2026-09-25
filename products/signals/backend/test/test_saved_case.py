from __future__ import annotations

import json
import hashlib
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

import pyarrow as pa
import pyarrow.parquet as pq
from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.models import EventDefinition, PropertyDefinition

from products.data_catalog.backend.facade.api import Metric, compute_drift
from products.posthog_ai.eval_harness.data_setup import create_empty_team
from products.posthog_ai.eval_harness.harness.django_env import NullDbBlocker
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalScoutConfig,
    SignalScoutRun,
    SignalScratchpad,
    SignalTeamConfig,
)
from products.signals.evals.agentic.saved_case import (
    EVENT_TABLE,
    STATE_MODELS,
    SavedCaseTransform,
    SavedEvent,
    SavedModel,
    SavedScoutCase,
    SavedState,
    state_table,
)
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

SOURCE = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
TARGET = datetime(2026, 2, 3, 14, 0, tzinfo=UTC)


def file_reference(path: Path) -> dict[str, str]:
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write_case(
    directory: Path,
    *,
    state: dict[str, object] | None = None,
    event_time: datetime | None = None,
    event_created_at: datetime | None = None,
    event_person_ids: list[UUID] | None = None,
    event_records: list[SavedEvent] | None = None,
) -> Path:
    def save(name: str, content: bytes) -> dict[str, str]:
        path = directory / name
        path.write_bytes(content)
        return file_reference(path)

    body = save("skill.md", b"Inspect the supplied API files and report reproducible defects.")
    saved_state = SavedState.model_validate(state or {"checkpoint": SOURCE.isoformat(), "complete": True})
    tables: dict[str, dict[str, str]] = {}
    for name in STATE_MODELS:
        value = cast(list[SavedModel] | SavedModel | None, getattr(saved_state, name))
        rows = [value] if isinstance(value, SavedModel) else value or []
        if rows:
            table_path = directory / f"{name}.parquet"
            state_table(name).write(table_path, rows)
            tables[name] = file_reference(table_path)
    state_metadata = saved_state.model_dump(mode="json", include={"checkpoint", "complete", "gaps", "timezone"})
    state_metadata["tables"] = tables
    events: list[dict[str, str]] = []
    records = event_records
    if records is None and event_time is not None:
        people: list[UUID | None] = [*event_person_ids] if event_person_ids else [None]
        records = [
            SavedEvent(
                uuid=uuid4(),
                timestamp=event_time,
                created_at=event_created_at or event_time,
                event="feedback",
                distinct_id="reader",
                person_id=person_id,
                properties={"rating": "negative"},
            )
            for person_id in people
        ]
    if records is not None:
        event_path = directory / "events.parquet"
        EVENT_TABLE.write(event_path, records)
        events.append(file_reference(event_path))
    manifest = {
        "schema_version": 2,
        "case_id": "invented-case",
        "source_cutoff": SOURCE.isoformat(),
        "investigation_start": (SOURCE - timedelta(days=1)).isoformat(),
        "skill": {"name": "signals-scout-fixture", "version": 7, "description": "Inspect API behavior.", "body": body},
        "state": state_metadata,
        "events": events,
        "time_strings": ["2026-01-01", "2026-01-02T11:00:00Z"],
    }
    path = directory / "case.json"
    path.write_text(json.dumps(manifest))
    return path


class TestSavedCaseValidation(SimpleTestCase):
    @parameterized.expand([2, 5001])
    def test_parquet_events_and_declared_time_strings(self, event_count: int) -> None:
        event_time = (SOURCE - timedelta(minutes=1)).replace(microsecond=123456)
        records = [
            SavedEvent(
                uuid=uuid4(),
                timestamp=event_time.astimezone(timezone(timedelta(hours=5, minutes=30))),
                created_at=(SOURCE - timedelta(seconds=1)).replace(microsecond=654321),
                event="feedback",
                distinct_id="000123",
                person_id=uuid4(),
                properties={
                    "rating": "negative",
                    "mixed": [None, False, 0, 1.25, "001", {}, [], {"value": ["a", 2]}],
                    "nested": {"empty": {}, "nothing": None},
                    "large_integer": 2**80,
                    "type_change": 1,
                },
            ),
            SavedEvent(
                uuid=uuid4(),
                timestamp=event_time,
                created_at=event_time,
                event="feedback",
                distinct_id="00123",
                properties={"type_change": "1"},
            ),
        ]
        records = (records * ((event_count + 1) // 2))[:event_count]
        with tempfile.TemporaryDirectory() as temporary:
            case = SavedScoutCase.load(write_case(Path(temporary), event_records=records))

            manifest_sha256 = hashlib.sha256(case.path.read_bytes()).hexdigest()
            case.path.write_text(case.path.read_text() + "\n")
            self.assertEqual(case.metadata["manifest_sha256"], manifest_sha256)
            restored = list(case.events())
            self.assertEqual(case.event_count, event_count)
            self.assertEqual(restored, records)
            self.assertIs(type(restored[0].properties["large_integer"]), int)
            self.assertEqual(restored[0].timestamp.utcoffset(), timedelta(0))
            transformed = SavedCaseTransform(case, TARGET)
            self.assertEqual(
                transformed.text("cursor 2026-01-02T11:00:00Z; other 2026-01-03"),
                "cursor 2026-02-03T13:00:00Z; other 2026-01-03",
            )
            self.assertEqual(transformed.text("day 2026-01-01"), "day 2026-02-02")
            self.assertEqual(
                transformed.text(
                    "2026-01-01T09:00:00Z; 2026-01-01 09:00:00; model-2026-01-01; /api/2026-01-01; day 2026-01-01."
                ),
                "2026-01-01T09:00:00Z; 2026-01-01 09:00:00; model-2026-01-01; /api/2026-01-01; day 2026-02-02.",
            )
            self.assertIn("exclude the end", case.run_note(TARGET))
            mixed_case = SavedScoutCase(
                case.path,
                case.manifest.model_copy(
                    update={
                        "string_replacements": {
                            "2026-01-02T11:00:00Z details": "timestamp replacement",
                            "2026-01-01 suffix": "date replacement",
                            "2026": "year replacement",
                        }
                    }
                ),
                case.state,
            )
            self.assertEqual(
                SavedCaseTransform(mixed_case, TARGET).text(
                    "2026-01-02T11:00:00Z details; 2026-01-02T11:00:00Z; "
                    "2026-01-01 suffix; 2026-01-01; model-2026-01-01"
                ),
                "timestamp replacement; 2026-02-03T13:00:00Z; "
                "date replacement; 2026-02-02; model-year replacement-01-01",
            )

    def test_parquet_history_preserves_json_and_empty_tables(self) -> None:
        report_id, task_id, task_run_id, scout_run_id, metric_id = [str(uuid4()) for _ in range(5)]
        created = (SOURCE - timedelta(hours=1)).isoformat()
        nested = {"mixed": [None, False, 1, 2.5, "001", {}, []], "large_integer": 2**80}
        state: dict[str, object] = {
            "checkpoint": SOURCE.isoformat(),
            "complete": True,
            "timezone": "America/New_York",
            "reports": [
                {
                    "id": report_id,
                    "created_at": created,
                    "status": "ready",
                    "charts": [nested],
                    "metrics": [None, {}, []],
                    "suggested_prompts": ["Review the recent events."],
                }
            ],
            "tasks": [{"id": task_id, "created_at": created, "state": nested}],
            "task_runs": [
                {
                    "id": task_run_id,
                    "task_id": task_id,
                    "created_at": created,
                    "status": "completed",
                    "output": [nested, None],
                    "state": nested,
                    "artifacts": [{"content": nested}],
                }
            ],
            "scout_runs": [
                {
                    "id": scout_run_id,
                    "task_run_id": task_run_id,
                    "created_at": created,
                    "skill_name": "signals-scout-fixture",
                    "skill_version": 7,
                    "emitted_report_ids": [report_id],
                    "edited_report_ids": [report_id],
                    "metadata": nested,
                }
            ],
            "metrics": [
                {
                    "id": metric_id,
                    "created_at": created,
                    "name": "event_count",
                    "description": "Number of events.",
                    "definition": nested,
                    "referenced_table_names": ["events"],
                    "status": "proposed",
                },
                {
                    "id": str(uuid4()),
                    "created_at": created,
                    "name": "unconfigured_metric",
                    "description": "A metric without a definition.",
                    "status": "proposed",
                },
            ],
            "project_profile": {
                "source_version": "fixture-v1",
                "payload": nested,
                "computed_at": created,
                "expires_at": (SOURCE + timedelta(days=1)).isoformat(),
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = write_case(directory, state=state, event_records=[])
            empty_table = directory / "scratchpad.parquet"
            state_table("scratchpad").write(empty_table, [])
            manifest = json.loads(path.read_text())
            manifest["state"]["tables"]["scratchpad"] = file_reference(empty_table)
            path.write_text(json.dumps(manifest))

            case = SavedScoutCase.load(path)

            self.assertEqual(case.state, SavedState.model_validate(state))
            self.assertEqual(case.event_count, 0)
            self.assertEqual(list(case.events()), [])

    @parameterized.expand(
        [
            "checksum",
            "event_checksum",
            "traversal",
            "upper_bound",
            "ingestion_upper_bound",
            "incomplete",
            "unknown_field",
            "unknown_state_table",
            "missing_reference",
            "source_insight",
            "old_schema",
            "missing_schema",
            "jsonl",
            "invalid_parquet",
            "wrong_type",
            "missing_column",
            "extra_column",
            "naive_timestamp",
            "invalid_properties",
            "invalid_uuid",
        ]
    )
    def test_invalid_cases_fail_during_load(self, failure: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            state: dict[str, object] = {"checkpoint": SOURCE.isoformat(), "complete": True}
            if failure == "incomplete":
                state["gaps"] = ["A required report is unavailable."]
            elif failure == "missing_reference":
                state["scratchpad"] = [
                    {
                        "id": str(uuid4()),
                        "key": "finding:fixture",
                        "content": "Saved",
                        "created_at": SOURCE.isoformat(),
                        "created_by_run_id": str(uuid4()),
                    }
                ]
            elif failure == "source_insight":
                state["metrics"] = [
                    {
                        "id": str(uuid4()),
                        "created_at": SOURCE.isoformat(),
                        "name": "event_count",
                        "description": "Number of events.",
                        "status": "approved",
                    }
                ]
            path = write_case(
                directory,
                state=state,
                event_time=SOURCE if failure == "upper_bound" else SOURCE - timedelta(seconds=1),
                event_created_at=SOURCE if failure == "ingestion_upper_bound" else None,
            )
            manifest = json.loads(path.read_text())
            event_path = directory / "events.parquet"
            if failure == "checksum":
                (directory / "skill.md").write_text("Different content")
            elif failure == "event_checksum":
                event_path.write_bytes(event_path.read_bytes() + b"changed")
            elif failure == "traversal":
                manifest["skill"]["body"]["path"] = "../skill.md"
            elif failure == "unknown_field":
                manifest["state"]["unsafe_model"] = "arbitrary.Object"
            elif failure == "unknown_state_table":
                manifest["state"]["tables"]["unsafe_model"] = file_reference(event_path)
            elif failure == "source_insight":
                metric_path = directory / "metrics.parquet"
                table = pq.read_table(metric_path)
                table = table.set_column(
                    table.schema.get_field_index("source_insight_short_id"),
                    "source_insight_short_id",
                    pa.array(["saved_link"]),
                )
                pq.write_table(table, metric_path)
                manifest["state"]["tables"]["metrics"] = file_reference(metric_path)
            elif failure == "old_schema":
                manifest["schema_version"] = 1
            elif failure == "missing_schema":
                del manifest["schema_version"]
            elif failure == "jsonl":
                jsonl_path = directory / "events.jsonl"
                record = next(EVENT_TABLE.read(event_path))
                jsonl_path.write_text(record.model_dump_json() + "\n")
                manifest["events"] = [file_reference(jsonl_path)]
            elif failure == "invalid_parquet":
                event_path.write_bytes(b"not parquet")
                manifest["events"] = [file_reference(event_path)]
            elif failure in {
                "wrong_type",
                "missing_column",
                "extra_column",
                "naive_timestamp",
                "invalid_properties",
                "invalid_uuid",
            }:
                table = pq.read_table(event_path)
                if failure == "wrong_type":
                    table = table.set_column(
                        table.schema.get_field_index("distinct_id"),
                        pa.field("distinct_id", pa.int64(), nullable=False),
                        pa.array([123]),
                    )
                elif failure == "missing_column":
                    table = table.drop_columns(["created_at"])
                elif failure == "extra_column":
                    table = table.append_column("team_id", pa.array([123]))
                elif failure == "naive_timestamp":
                    table = table.set_column(
                        table.schema.get_field_index("timestamp"),
                        pa.field("timestamp", pa.timestamp("us"), nullable=False),
                        pa.array([(SOURCE - timedelta(seconds=1)).replace(tzinfo=None)]),
                    )
                else:
                    column = "properties" if failure == "invalid_properties" else "uuid"
                    table = table.set_column(
                        table.schema.get_field_index(column),
                        table.schema.field(column),
                        pa.array(["{" if failure == "invalid_properties" else "not-a-uuid"]),
                    )
                pq.write_table(table, event_path)
                manifest["events"] = [file_reference(event_path)]
            path.write_text(json.dumps(manifest))

            with self.assertRaises(ValueError):
                SavedScoutCase.load(path)


class TestSavedCaseRestore(BaseTest):
    def test_restore_preserves_history_and_isolates_local_writes(self) -> None:
        self.organization.name = "Eval (saved-case-test)"
        self.organization.save(update_fields=["name"])
        report_id, task_id, task_run_id, scout_run_id, memory_id, artefact_id = [str(uuid4()) for _ in range(6)]
        metric_id = str(uuid4())
        metric_definition = {"kind": "HogQLQuery", "query": "SELECT count() FROM events"}
        created = (SOURCE - timedelta(hours=1)).isoformat()
        state = {
            "checkpoint": SOURCE.isoformat(),
            "complete": True,
            "metrics": [
                {
                    "id": metric_id,
                    "created_at": created,
                    "updated_at": created,
                    "name": "event_count",
                    "description": "Number of events.",
                    "definition": metric_definition,
                    "referenced_table_names": ["events"],
                    "status": "approved",
                    "approved_at": created,
                    "approved_by_id": 123,
                }
            ],
            "reports": [
                {
                    "id": report_id,
                    "created_at": created,
                    "updated_at": created,
                    "status": "ready",
                    "title": "API validation",
                    "summary": "Input validation is incomplete.",
                }
            ],
            "tasks": [{"id": task_id, "created_at": created, "title": "Prior investigation"}],
            "task_runs": [
                {
                    "id": task_run_id,
                    "task_id": task_id,
                    "created_at": created,
                    "status": "completed",
                    "completed_at": created,
                }
            ],
            "scout_runs": [
                {
                    "id": scout_run_id,
                    "task_run_id": task_run_id,
                    "created_at": created,
                    "skill_name": "signals-scout-fixture",
                    "skill_version": 7,
                    "emitted_report_ids": [report_id],
                }
            ],
            "scratchpad": [
                {
                    "id": memory_id,
                    "created_at": created,
                    "updated_at": created,
                    "key": "finding:fixture",
                    "content": f"Report {report_id}; cursor 2026-01-02T11:00:00Z",
                    "created_by_run_id": scout_run_id,
                    "expires_at": (SOURCE + timedelta(days=2)).isoformat(),
                }
            ],
            "report_artefacts": [
                {
                    "id": artefact_id,
                    "created_at": created,
                    "report_id": report_id,
                    "type": "note",
                    "content": json.dumps({"text": f"Source run {scout_run_id}"}),
                    "task_id": task_id,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            case = SavedScoutCase.load(write_case(Path(temporary), state=state))
            context = CustomPromptSandboxContext(team_id=self.team.id, user_id=self.user.id)

            result = case.restore(context, target_cutoff=TARGET)

            report = SignalReport.objects.get(team_id=self.team.id)
            memory = SignalScratchpad.objects.for_team(self.team.id).get()
            run = SignalScoutRun.objects.for_team(self.team.id).get()
            artefact = SignalReportArtefact.objects.get(team_id=self.team.id)
            self.assertNotEqual(str(report.id), report_id)
            self.assertEqual(run.emitted_report_ids, [str(report.id)])
            self.assertEqual(memory.created_by_run_id, run.id)
            self.assertEqual(artefact.report_id, report.id)
            self.assertIn(str(run.id), artefact.content)
            self.assertIn(str(report.id), memory.content)
            self.assertIn("2026-02-03T13:00:00Z", memory.content)
            self.assertEqual(memory.updated_at, TARGET - timedelta(hours=1))
            self.assertEqual(memory.expires_at, TARGET + timedelta(days=2))
            config = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name=case.skill_name)
            self.assertFalse(config.enabled)
            self.assertTrue(config.emit)
            self.assertEqual(config.write_scopes, [])
            team_config = SignalTeamConfig.objects.get(team_id=self.team.id)
            self.assertFalse(team_config.autostart_enabled)
            self.assertFalse(team_config.github_issue_writeback_enabled)
            self.assertEqual(result["restored_reports"], 1)
            metric = Metric.objects.for_team(self.team.id).get()
            self.assertNotEqual(str(metric.id), metric_id)
            self.assertEqual(metric.definition, metric_definition)
            self.assertEqual(metric.status, "approved")
            self.assertEqual(metric.approved_at, TARGET - timedelta(hours=1))
            self.assertEqual(metric.approved_by_id, self.user.id)
            self.assertFalse(compute_drift([metric])[metric.id])
            self.organization.refresh_from_db()
            self.user.refresh_from_db()
            self.assertEqual(self.organization.name, "Workspace")
            self.assertEqual(self.user.email, f"member-{self.user.id}@example.com")
            self.assertEqual(self.user.first_name, "Project member")
            with self.assertRaisesRegex(ValueError, "fresh empty project"):
                case.restore(context, target_cutoff=TARGET)


class TestSavedCaseEventRestore(ClickhouseTestMixin, BaseTest):
    def test_repeated_restore_isolates_events_and_preserves_ingestion_time(self) -> None:
        self.organization.name = "Eval (saved-event-test)"
        self.organization.save(update_fields=["name"])
        other_project = create_empty_team(NullDbBlocker(), label="second-trial")
        target = datetime.now(UTC).replace(microsecond=0)
        event_time = (SOURCE - timedelta(minutes=1)).replace(microsecond=123456)
        created_at = (SOURCE - timedelta(seconds=30)).replace(microsecond=654321)
        expected_timestamp = event_time + (target - SOURCE)
        expected_created_at = created_at + (target - SOURCE)
        person_ids = [uuid4(), uuid4()]
        with tempfile.TemporaryDirectory() as temporary:
            case = SavedScoutCase.load(
                write_case(
                    Path(temporary),
                    event_time=event_time,
                    event_created_at=created_at,
                    event_person_ids=person_ids,
                )
            )
            source_ids = {str(event.uuid): str(event.person_id) for event in case.events()}
            for team, user in ((self.team, self.user), (other_project.team, other_project.user)):
                result = case.restore(
                    CustomPromptSandboxContext(team_id=team.id, user_id=user.id), target_cutoff=target
                )

                rows = sync_execute(
                    "SELECT uuid, timestamp, created_at, person_id FROM events WHERE team_id = %(team_id)s",
                    {"team_id": team.id},
                )
                self.assertEqual(len(rows), 2)
                self.assertEqual({str(row[0]): str(row[3]) for row in rows}, source_ids)
                for row in rows:
                    self.assertEqual(row[1].replace(tzinfo=UTC), expected_timestamp)
                    self.assertEqual(row[2].replace(tzinfo=UTC), expected_created_at)
                self.assertEqual(result["restored_events"], 2)
                timestamp_string = expected_timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                self.assertEqual(
                    result["event_validation"],
                    {
                        "matched": True,
                        "query_performed": True,
                        "by_event": {
                            "feedback": {
                                "count": 2,
                                "min_timestamp": timestamp_string,
                                "max_timestamp": timestamp_string,
                            }
                        },
                    },
                )
                self.assertTrue(EventDefinition.objects.filter(team_id=team.id, name="feedback").exists())
                self.assertTrue(PropertyDefinition.objects.filter(team_id=team.id, name="rating").exists())
                query = execute_hogql_query("SELECT event, distinct_id, properties.rating FROM events", team=team)
                self.assertEqual(query.results, [("feedback", "reader", "negative")] * 2)
