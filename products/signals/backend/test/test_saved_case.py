from __future__ import annotations

import gzip
import json
import hashlib
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.models import EventDefinition, PropertyDefinition

from products.data_catalog.backend.logic.drift import compute_drift
from products.data_catalog.backend.models import Metric
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
from products.signals.evals.agentic.saved_case import SavedCaseTransform, SavedScoutCase
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

SOURCE = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
TARGET = datetime(2026, 2, 3, 14, 0, tzinfo=UTC)


def write_case(
    directory: Path,
    *,
    state: dict | None = None,
    event_time: datetime | None = None,
    event_created_at: datetime | None = None,
    event_person_ids: list[UUID] | None = None,
) -> Path:
    def save(name: str, content: bytes) -> dict[str, str]:
        (directory / name).write_bytes(content)
        return {"path": name, "sha256": hashlib.sha256(content).hexdigest()}

    body = save("skill.md", b"Inspect the supplied API files and report reproducible defects.")
    state_file = save("state.json", json.dumps(state or {"checkpoint": SOURCE.isoformat(), "complete": True}).encode())
    events = []
    if event_time is not None:
        people: list[UUID | None] = [*event_person_ids] if event_person_ids else [None]
        records = [
            {
                "uuid": str(uuid4()),
                "timestamp": event_time.isoformat(),
                "created_at": (event_created_at or event_time).isoformat(),
                "event": "feedback",
                "distinct_id": "reader",
                "person_id": str(person_id) if person_id else None,
                "properties": json.dumps({"rating": "negative"}),
            }
            for person_id in people
        ]
        events.append(
            save("events.jsonl.gz", gzip.compress("".join(json.dumps(row) + "\n" for row in records).encode()))
        )
    manifest = {
        "case_id": "invented-case",
        "source_cutoff": SOURCE.isoformat(),
        "investigation_start": (SOURCE - timedelta(days=1)).isoformat(),
        "skill": {"name": "signals-scout-fixture", "version": 7, "description": "Inspect API behavior.", "body": body},
        "state": state_file,
        "events": events,
        "time_strings": ["2026-01-01", "2026-01-02T11:00:00Z"],
    }
    path = directory / "case.json"
    path.write_text(json.dumps(manifest))
    return path


class TestSavedCaseValidation(SimpleTestCase):
    def test_compressed_events_and_declared_time_strings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = SavedScoutCase.load(write_case(Path(temporary), event_time=SOURCE - timedelta(seconds=1)))

            self.assertEqual(case.event_count, 1)
            self.assertEqual(next(case.events()).properties, {"rating": "negative"})
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

    @parameterized.expand(
        ["checksum", "traversal", "upper_bound", "incomplete", "unknown_field", "missing_reference", "source_insight"]
    )
    def test_invalid_cases_fail_during_load(self, failure: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            state: dict = {"checkpoint": SOURCE.isoformat(), "complete": True}
            if failure == "incomplete":
                state["gaps"] = ["A required report is unavailable."]
            elif failure == "unknown_field":
                state["unsafe_model"] = "arbitrary.Object"
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
                        "source_insight_short_id": "saved_link",
                    }
                ]
            path = write_case(directory, state=state, event_time=SOURCE if failure == "upper_bound" else None)
            if failure == "checksum":
                (directory / "skill.md").write_text("Different content")
            elif failure == "traversal":
                manifest = json.loads(path.read_text())
                manifest["skill"]["body"]["path"] = "../skill.md"
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
        _, other_team, other_user = create_empty_team(NullDbBlocker(), label="second-trial")
        target = datetime.now(UTC).replace(microsecond=0)
        person_ids = [uuid4(), uuid4()]
        with tempfile.TemporaryDirectory() as temporary:
            case = SavedScoutCase.load(
                write_case(
                    Path(temporary),
                    event_time=SOURCE - timedelta(minutes=1),
                    event_created_at=SOURCE - timedelta(seconds=30),
                    event_person_ids=person_ids,
                )
            )
            source_ids = {str(event.uuid): str(event.person_id) for event in case.events()}
            for team, user in ((self.team, self.user), (other_team, other_user)):
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
                    self.assertEqual(row[1].replace(tzinfo=UTC), target - timedelta(minutes=1))
                    self.assertEqual(row[2].replace(tzinfo=UTC), target - timedelta(seconds=30))
                self.assertEqual(result["restored_events"], 2)
                expected_timestamp = (target - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                self.assertEqual(
                    result["event_validation"],
                    {
                        "matched": True,
                        "query_performed": True,
                        "by_event": {
                            "feedback": {
                                "count": 2,
                                "min_timestamp": expected_timestamp,
                                "max_timestamp": expected_timestamp,
                            }
                        },
                    },
                )
                self.assertTrue(EventDefinition.objects.filter(team_id=team.id, name="feedback").exists())
                self.assertTrue(PropertyDefinition.objects.filter(team_id=team.id, name="rating").exists())
                query = execute_hogql_query("SELECT event, distinct_id, properties.rating FROM events", team=team)
                self.assertEqual(query.results, [("feedback", "reader", "negative")] * 2)
