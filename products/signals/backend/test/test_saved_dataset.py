from __future__ import annotations

import json
import hashlib
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.evals.agentic.saved_case import (
    EVENT_TABLE,
    STATE_MODELS,
    SavedEvent,
    SavedModel,
    SavedScoutCase,
    SavedState,
    state_table,
)
from products.signals.evals.agentic.saved_dataset import SavedScoutDataset

SOURCE = datetime(2030, 6, 4, 12, tzinfo=UTC)


def write_dataset_case(
    directory: Path,
    skill_name: str,
    *,
    state: dict[str, object] | None = None,
    events: list[SavedEvent] | None = None,
    manifest_changes: dict[str, object] | None = None,
) -> SavedScoutCase:
    directory.mkdir()

    def reference(path: Path) -> dict[str, str]:
        return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    body = directory / "skill.md"
    body.write_text(f"Inspect the invented delivery queue using {skill_name}.")
    support = directory / "guide.txt"
    support.write_text('A queue item with status "waiting" has not been delivered.\n')
    saved_state = SavedState.model_validate(state or {"checkpoint": SOURCE, "complete": True})
    tables = {}
    for name in STATE_MODELS:
        value = cast(list[SavedModel] | SavedModel | None, getattr(saved_state, name))
        rows = [value] if isinstance(value, SavedModel) else value or []
        if rows:
            path = directory / f"{name}.parquet"
            state_table(name).write(path, rows)
            tables[name] = reference(path)
    event_path = directory / "events.parquet"
    EVENT_TABLE.write(event_path, events or [])
    state_manifest = saved_state.model_dump(mode="json", include={"checkpoint", "complete", "gaps", "timezone"})
    state_manifest["tables"] = tables
    manifest: dict[str, object] = {
        "schema_version": 2,
        "case_id": skill_name,
        "source_team_id": 123,
        "source_cutoff": SOURCE.isoformat(),
        "skill": {
            "name": skill_name,
            "version": 1,
            "description": "Inspect an invented queue.",
            "body": reference(body),
            "files": [{"path": "guide.txt", "content": reference(support)}],
        },
        "state": state_manifest,
        "events": [reference(event_path)],
        **(manifest_changes or {}),
    }
    path = directory / "case.json"
    path.write_text(json.dumps(manifest))
    return SavedScoutCase.load(path)


def delivery_event(identifier: UUID | None = None, *, label: str = "parcel-a") -> SavedEvent:
    return SavedEvent(
        uuid=identifier or uuid4(),
        timestamp=SOURCE - timedelta(minutes=5),
        created_at=SOURCE - timedelta(minutes=4),
        event="delivery_queued",
        distinct_id="invented-reader",
        properties={"label": label, "details": 'The queue returned "waiting".\nRetry later.'},
    )


class TestSavedDatasetPreparation(SimpleTestCase):
    @parameterized.expand([1, 2])
    def test_prepared_dataset_retains_deduplicated_rows_skills_and_provenance(self, count: int) -> None:
        shared_event = delivery_event()
        report_id = uuid4()
        state: dict[str, object] = {
            "checkpoint": SOURCE,
            "complete": True,
            "reports": [{"id": report_id, "created_at": SOURCE, "status": "ready", "summary": "Queue is waiting."}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = [
                write_dataset_case(
                    root / f"source-{index}",
                    f"signals-scout-queue-{index}",
                    state=state,
                    events=[shared_event, delivery_event(label=f"parcel-{index}")],
                    manifest_changes={"source_team_id": None} if count == 1 else None,
                )
                for index in range(count)
            ]
            source_hashes = [case.manifest_sha256 for case in cases]
            prepared = SavedScoutDataset.prepare(cases, root / "prepared")
            loaded = SavedScoutDataset.load(prepared.path)

            self.assertEqual(loaded.metadata, prepared.metadata)
            self.assertEqual(loaded.manifest.event_count, count + 1)
            self.assertEqual(loaded.metadata["deduplicated_event_count"], count - 1)
            self.assertEqual([source.manifest_sha256 for source in loaded.manifest.sources], source_hashes)
            self.assertEqual([case.skill_name for case in loaded.cases], [case.skill_name for case in cases])
            self.assertEqual(loaded.manifest.state_counts["reports"], 1)
            self.assertEqual(loaded.cases[0].state.reports[0].id, report_id)
            self.assertEqual(next(loaded.cases[0].events()), shared_event)
            self.assertEqual([case.manifest_sha256 for case in cases], source_hashes)
            for case in loaded.cases:
                self.assertIn(case.skill_name, case.manifest.skill.body.resolve(case.path.parent).read_text())
                self.assertEqual(case.manifest.skill.files[0].path, "guide.txt")
                self.assertEqual(case.state, loaded.cases[0].state)
            self.assertEqual(prepared.path.parent.stat().st_mode & 0o777, 0o700)
            self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in prepared.path.parent.iterdir()))

            cases[0].manifest.skill.body.resolve(cases[0].path.parent).write_text("Source changed after preparation.")
            self.assertEqual(SavedScoutDataset.load(prepared.path).metadata, loaded.metadata)
            with self.assertRaisesRegex(ValueError, "new or empty"):
                SavedScoutDataset.prepare(loaded.cases, prepared.path.parent)

    @parameterized.expand(
        [
            "project",
            "unknown_project",
            "cutoff",
            "checkpoint",
            "timezone",
            "replacement_policy",
            "same_skill",
            "repository_commit",
            "row_payload",
            "scratchpad_key",
            "profile",
            "event_payload",
        ]
    )
    def test_conflicting_cases_fail_before_dataset_becomes_restorable(self, conflict: str) -> None:
        event = delivery_event()
        row_id = uuid4()
        initial_state: dict[str, object] = {
            "checkpoint": SOURCE,
            "complete": True,
            "scratchpad": [{"id": row_id, "created_at": SOURCE - timedelta(days=1), "key": "queue", "content": "Wait"}],
        }
        other_state: dict[str, object] = dict(initial_state)
        first_changes: dict[str, object] = {}
        changes: dict[str, object] = {}
        if conflict == "project":
            changes["source_team_id"] = 456
        elif conflict == "unknown_project":
            first_changes["source_team_id"] = None
            changes["source_team_id"] = None
        elif conflict == "cutoff":
            changes["source_cutoff"] = (SOURCE + timedelta(hours=1)).isoformat()
        elif conflict == "checkpoint":
            other_state["checkpoint"] = SOURCE - timedelta(hours=1)
        elif conflict == "timezone":
            other_state["timezone"] = "Europe/Paris"
        elif conflict == "replacement_policy":
            changes["time_strings"] = ["2030-06-04"]
        elif conflict == "repository_commit":
            repository = {"name": "posthog/invented-queue", "source_path": "/tmp/invented-queue", "commit": "a" * 40}
            first_changes["repository"] = repository
            changes["repository"] = {**repository, "commit": "b" * 40}
        elif conflict in {"row_payload", "scratchpad_key"}:
            other_state["scratchpad"] = [
                {
                    "id": row_id if conflict == "row_payload" else uuid4(),
                    "created_at": SOURCE - timedelta(days=1),
                    "key": "queue",
                    "content": "Deliver",
                }
            ]
        elif conflict == "profile":
            profile = {"source_version": "invented", "payload": {}, "computed_at": SOURCE, "expires_at": SOURCE}
            initial_state["project_profile"] = profile
            other_state["project_profile"] = {**profile, "payload": {"queue": "different"}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = write_dataset_case(
                root / "first",
                "signals-scout-queue",
                state=initial_state,
                events=[event],
                manifest_changes=first_changes,
            )
            second = write_dataset_case(
                root / "second",
                first.skill_name if conflict == "same_skill" else "signals-scout-deliveries",
                state=other_state,
                events=[delivery_event(event.uuid, label="parcel-b")] if conflict == "event_payload" else [event],
                manifest_changes=changes,
            )
            workspace = root / "prepared"
            with self.assertRaises(ValueError):
                SavedScoutDataset.prepare([first, second], workspace)
            self.assertFalse((workspace / "dataset.json").exists())

    def test_changed_prepared_content_fails_before_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = write_dataset_case(root / "source", "signals-scout-queue", events=[delivery_event()])
            prepared = SavedScoutDataset.prepare([case], root / "prepared")
            (prepared.path.parent / "events.parquet").write_bytes(b"changed")

            with self.assertRaisesRegex(ValueError, "checksum"):
                SavedScoutDataset.load(prepared.path)
