from __future__ import annotations

import sys
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import time_machine
from unittest.mock import patch

from django.test import SimpleTestCase

import httpx
from parameterized import parameterized
from pydantic import JsonValue, ValidationError

from products.posthog_ai.eval_harness.environment.schema import EVENT_TABLE, METRIC_TABLE
from products.signals.backend.scout_harness.eval_environment.schema import ScoutEnvironmentCase
from products.signals.backend.scout_harness.eval_environment.source import SourceEnvironmentExporter, SourceEvents
from products.signals.backend.scout_harness.eval_environment.source_client import SourceAPI, SourceExportError
from products.signals.backend.scout_harness.eval_environment.source_plan import (
    SourceEventWindow,
    SourcePropertyFilter,
    SourceSlicePlan,
)
from products.signals.backend.scout_harness.profile_version import INVENTORY_SOURCE_VERSION


class SourceFixture:
    cutoff = datetime(2030, 1, 2, 12, tzinfo=UTC)
    skill_id = "00000000-0000-4000-8000-000000000001"
    config_id = "00000000-0000-4000-8000-000000000002"
    profile_id = "00000000-0000-4000-8000-000000000003"
    report_id = "00000000-0000-4000-8000-000000000004"
    user_id = "00000000-0000-4000-8000-000000000005"
    note_id = "00000000-0000-4000-8000-000000000006"
    artefact_id = "00000000-0000-4000-8000-000000000007"
    metric_id = "00000000-0000-4000-8000-000000000008"

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.pages = 0
        self.drift = False
        self.empty_page = False
        self.unknown_author = False
        self.report_status = "ready"
        self.work_state = "unclaimed"
        self.destination: dict[str, JsonValue] = {"slack": None, "webhook": None, "inbox": True}
        self.skill_body = "Read events."
        self.user: dict[str, JsonValue] = {
            "id": 1,
            "uuid": self.user_id,
            "first_name": "Sample",
            "last_name": "Owner",
            "email": "owner@example.com",
        }
        self.date = (self.cutoff - timedelta(days=1)).isoformat()
        self.old_date = (self.cutoff - timedelta(days=365)).isoformat()
        self.profile: dict[str, JsonValue] = {
            "source_origin": "https://source.example.com",
            "project_id": 12,
            "captured_at": (self.cutoff - timedelta(seconds=1)).isoformat(),
            "profile": {
                "profile_id": self.profile_id,
                "computed_at": self.date,
                "expires_at": (self.cutoff + timedelta(hours=1)).isoformat(),
                "source_version": INVENTORY_SOURCE_VERSION,
                "payload": {"inventory": {"created_at": self.date}},
            },
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/projects/12/")
        if path == "query/":
            query = json.loads(request.content)["query"]["query"]
            if query.startswith("SELECT count()"):
                return httpx.Response(200, json={"results": [[2, 2]]})
            index = self.pages % 2
            changed = self.drift and self.pages >= 2
            self.pages += 1
            row: list[JsonValue] = [
                f"00000000-0000-4000-8000-00000000001{index}",
                "2030-01-01 12:00:00.123456",
                "example_event",
                "source-visitor",
                None,
                {"quality": "changed" if changed else "observed"},
                "2030-01-01 12:00:01.654321",
            ]
            return httpx.Response(200, json={"results": [] if self.empty_page else [row]})
        if request.url.path == "/api/users/@me/":
            return httpx.Response(
                200,
                json={
                    **self.user,
                    "organization": {
                        "id": "example-org",
                        "name": "Example organization",
                        "is_ai_data_processing_approved": True,
                        "is_ai_training_opted_in": False,
                    },
                },
            )
        if path == "":
            return httpx.Response(
                200,
                json={
                    "id": 12,
                    "name": "Example project",
                    "timezone": "America/Los_Angeles",
                    "organization": "example-org",
                },
            )
        if path == "signals/scout/configs/":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": self.config_id,
                        "skill_name": "example-scout",
                        "emit": True,
                        "scout_origin": "custom",
                        "output_destinations": self.destination,
                    }
                ],
            )
        if path == f"signals/scout/rubrics/{self.config_id}/":
            return httpx.Response(
                200,
                json={
                    "config_id": self.config_id,
                    "skill_name": "example-scout",
                    "revision": 3,
                    "criteria": [],
                    "generation": None,
                },
            )
        if path in {"llm_skills/name/example-scout/", "llm_skills/name/example-companion/"}:
            companion = path == "llm_skills/name/example-companion/"
            return httpx.Response(
                200,
                json={
                    "id": "00000000-0000-4000-8000-000000000009" if companion else self.skill_id,
                    "name": "example-companion" if companion else "example-scout",
                    "description": "Inspect example events.",
                    "body": self.skill_body,
                    "body_total_length": len(self.skill_body),
                    "body_next_offset": None,
                    "version": 1,
                    "files": [],
                    "owners": [self.user],
                    "created_by": self.user,
                    "created_at": self.date,
                    "updated_at": self.date,
                    "allowed_tools": ["emit_report"],
                    "metadata": {},
                },
            )
        if path == "data_catalog/metrics/example_metric/":
            return httpx.Response(
                200,
                json={
                    "id": self.metric_id,
                    "name": "example_metric",
                    "description": "Invented example metric.",
                    "status": "approved",
                    "created_at": self.date,
                    "updated_at": self.date,
                    "created_by": self.user,
                    "approved_by": self.user,
                    "approved_at": self.date,
                    "owner": self.user["email"],
                    "referenced_table_names": ["events"],
                },
            )
        if path == "signals/scout/notes/":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": self.note_id,
                        "skill_name": "example-scout",
                        "content": "Check the complete selected window.",
                        "created_by_name": "Unknown Owner" if self.unknown_author else "Sample Owner",
                        "created_at": self.old_date,
                        "expires_at": None,
                        "origin": "human",
                    }
                ],
            )
        if path == "signals/scout/scratchpad/":
            return httpx.Response(
                200,
                json=[
                    {
                        "key": "pattern:example",
                        "content": "Previously observed example.",
                        "created_at": self.old_date,
                        "updated_at": self.old_date,
                        "expires_at": None,
                        "created_by_run_id": None,
                        "created_by_skill": "example-scout",
                    }
                ],
            )
        if path == "signals/scout/runs/":
            return httpx.Response(200, json=[])
        if path == f"signals/reports/{self.report_id}/":
            return httpx.Response(
                200,
                json={
                    "id": self.report_id,
                    "title": "Example finding",
                    "summary": "Invented example.",
                    "status": self.report_status,
                    "work_state": self.work_state,
                    "created_at": self.date,
                    "updated_at": self.date,
                },
            )
        if path == f"signals/reports/{self.report_id}/artefacts/":
            return httpx.Response(
                200,
                json={
                    "next": None,
                    "results": [
                        {
                            "id": self.artefact_id,
                            "created_at": self.date,
                            "updated_at": self.date,
                            "type": "note",
                            "content": {"message": "Example note."},
                            "actor_kind": "user",
                            "actor_agent": None,
                            "task_id": None,
                            "claim_id": None,
                            "created_by": self.user,
                        }
                    ],
                },
            )
        raise AssertionError("Unexpected source read: " + request.url.path)

    def plan(self, directory: Path, *, purpose: str = "scout") -> SourceSlicePlan:
        profile = directory / "profile.json"
        profile.write_text(json.dumps(self.profile))
        return SourceSlicePlan.model_validate(
            {
                "environment_id": "example-source",
                "purpose": purpose,
                "project_id": 12,
                "skill_name": "example-scout",
                "profile_snapshot": str(profile),
                "event_windows": [{"start": self.date, "end": self.cutoff.isoformat(), "events": ["example_event"]}],
                "history_from": self.date,
                "source_cutoff": self.cutoff.isoformat(),
                "dependencies": ["events", "scout_context"] if purpose == "scout" else ["events"],
                "selection_reason": "Example events and the selected scout's starting context.",
                "report_ids": [self.report_id],
                "memory_keys": ["pattern:example"],
                "page_size": 1,
                "text_time_policy_reviewed": True,
            }
        )


@time_machine.travel(SourceFixture.cutoff, tick=False)
class TestSourceExport(SimpleTestCase):
    def api(self, fixture: SourceFixture) -> SourceAPI:
        with patch.dict("os.environ", {"EXAMPLE_SOURCE_TOKEN": "phx_example_not_a_real_token"}):
            api = SourceAPI(
                "https://source.example.com",
                token_env="EXAMPLE_SOURCE_TOKEN",
                project_id=12,
                transport=httpx.MockTransport(fixture.handle),
            )
        self.addCleanup(api.close)
        return api

    def test_source_command_help_runs_without_django_setup(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "products.signals.backend.scout_harness.eval_environment.source", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "--token-env" in result.stdout

    def test_exports_complete_source_data_and_current_scout_context(self) -> None:
        fixture = SourceFixture()
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            plan = fixture.plan(directory).model_copy(update={"companion_skill_names": ["example-companion"]})
            output = directory / "export"
            result = SourceEnvironmentExporter(self.api(fixture), plan).export(output)
            rows = list(EVENT_TABLE.read(output / "events.parquet"))
            case = ScoutEnvironmentCase.model_validate_json((output / "case.json").read_bytes())
            assert len(rows) == result["event_count"] == 2
            assert rows[0].timestamp.microsecond == 123456
            assert rows[0].created_at.microsecond == 654321
            assert rows[0].properties == {"quality": "observed"}
            assert case.prompt_mode == "native" and case.timezone == "America/Los_Angeles"
            assert [skill.name for skill in case.companion_skills] == ["example-companion"]
            assert case.companion_skills[0].body == fixture.skill_body
            assert case.companion_skills[0].owners == ["1"]
            assert case.config["output_destinations"] == {"slack": None, "webhook": None, "inbox": True}
            rubrics = case.config["rubrics"]
            assert isinstance(rubrics, dict) and rubrics["revision"] == 3
            assert case.organization.is_ai_data_processing_approved is True
            assert case.state.notes[0].fields["created_by_id"] == "1"
            assert case.state.notes[0].created_at < plan.history_from
            assert case.state.memory[0].created_at < plan.history_from
            artefact_content = case.state.report_artefacts[0].fields["content"]
            assert isinstance(artefact_content, str) and json.loads(artefact_content) == {"message": "Example note."}
            assert fixture.date in case.time_strings
            memory_reads = [request for request in fixture.requests if request.url.path.endswith("scratchpad/")]
            assert all(request.url.params["key"] == "pattern:example" for request in memory_reads)
            assert not any("project_profile" in request.url.path for request in fixture.requests)
            assert result["synthetic_rows"] == 0 and result["runnable_scout"] is True
            assert not any("phx_example" in path.read_text(errors="ignore") for path in output.iterdir())
            with self.assertRaises(FileExistsError):
                SourceEnvironmentExporter(self.api(fixture), plan).export(output)

    @parameterized.expand(
        [("drift", "changed during export"), ("empty_page", "ended before"), ("unknown_author", "author cannot")]
    )
    def test_failed_export_never_publishes_partial_output(self, failure: str, message: str) -> None:
        fixture = SourceFixture()
        setattr(fixture, failure, True)
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            output = directory / "export"
            with self.assertRaisesRegex(SourceExportError, message):
                SourceEnvironmentExporter(self.api(fixture), fixture.plan(directory)).export(output)
            assert not output.exists()
            assert not list(directory.glob(".scout-source-*"))

    def test_events_only_output_is_explicitly_not_a_runnable_scout(self) -> None:
        fixture = SourceFixture()
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            output = directory / "export"
            result = SourceEnvironmentExporter(
                self.api(fixture), fixture.plan(directory, purpose="events_only")
            ).export(output)
            assert result["runnable_scout"] is False
            assert not (output / "case.json").exists()
            assert all(request.url.path.endswith("query/") for request in fixture.requests)

    @parameterized.expand([("source_version", "old-version"), ("expires_at", "2029-12-31T00:00:00+00:00")])
    def test_unusable_profile_stops_before_source_reads(self, field: str, value: str) -> None:
        fixture = SourceFixture()
        profile = fixture.profile["profile"]
        assert isinstance(profile, dict)
        profile[field] = value
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaises(SourceExportError):
                SourceEnvironmentExporter(self.api(fixture), fixture.plan(directory)).export(directory / "export")
        assert fixture.requests == []

    @parameterized.expand([(False,), (True,)])
    def test_metrics_preserve_source_values_and_reject_unmapped_context_links(self, uuid_link: bool) -> None:
        fixture = SourceFixture()
        fixture.skill_body = "Read metric " + (fixture.metric_id if uuid_link else "example_metric") + "."
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            plan = SourceSlicePlan.model_validate(
                {
                    **fixture.plan(directory).model_dump(),
                    "metric_names": ["example_metric"],
                    "dependencies": ["events", "scout_context", "data_catalog_metrics"],
                }
            )
            exporter = SourceEnvironmentExporter(self.api(fixture), plan)
            output = directory / "export"
            if uuid_link:
                with self.assertRaisesRegex(SourceExportError, "source metric UUID"):
                    exporter.export(output)
                assert not output.exists()
                assert not any(request.url.path.endswith("query/") for request in fixture.requests)
            else:
                result = exporter.export(output)
                metrics = list(METRIC_TABLE.read(output / "metrics.parquet"))
                assert result["metric_count"] == 1
                assert metrics[0].name == "example_metric"
                assert str(metrics[0].id) == fixture.metric_id
                assert metrics[0].owner_id == metrics[0].created_by_id == metrics[0].approved_by_id == 1

    def test_draft_skill_exports_without_prior_scout_configuration(self) -> None:
        fixture = SourceFixture()
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            skill = directory / "SKILL.md"
            skill.write_text("---\nname: example-scout\nallowed-tools: emit_report\n---\nRead example events.\n")
            references = directory / "references"
            references.mkdir()
            (references / "example.md").write_text("Invented companion reference.\n")
            plan = SourceSlicePlan.model_validate({**fixture.plan(directory).model_dump(), "draft_skill": skill})
            SourceEnvironmentExporter(self.api(fixture), plan).export(directory / "export")
            case = ScoutEnvironmentCase.model_validate_json((directory / "export" / "case.json").read_bytes())
            assert case.skill.body == "Read example events.\n"
            assert case.skill.files == {"references/example.md": "Invented companion reference.\n"}
            assert case.skill.origin == "custom"
            assert not any(
                "configs/" in request.url.path or "llm_skills/" in request.url.path for request in fixture.requests
            )

    def test_unsupported_capability_stops_before_event_export(self) -> None:
        fixture = SourceFixture()
        fixture.destination = {"webhook": {"url": "https://example.com/hook"}}
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            plan = fixture.plan(directory)
            with self.assertRaisesRegex(SourceExportError, "unsupported isolated adapter"):
                SourceEnvironmentExporter(self.api(fixture), plan).export(directory / "export")
            assert not any(request.url.path.endswith("query/") for request in fixture.requests)
            with self.assertRaisesRegex(ValidationError, "Unsupported source dependencies"):
                SourceSlicePlan.model_validate(
                    {**plan.model_dump(), "dependencies": ["events", "scout_context", "persons"]}
                )

    @parameterized.expand([("ready", "working"), ("ready", "in_review"), ("resolved", "unclaimed")])
    def test_report_work_state_must_be_reproducible_without_missing_assignments(
        self, status: str, work_state: str
    ) -> None:
        fixture = SourceFixture()
        fixture.report_status = status
        fixture.work_state = work_state
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaisesRegex(SourceExportError, "unsupported task channels"):
                SourceEnvironmentExporter(self.api(fixture), fixture.plan(directory)).export(directory / "export")
        assert not any(request.url.path.endswith("query/") for request in fixture.requests)

    def test_quoted_event_names_and_property_values_remain_literals(self) -> None:
        fixture = SourceFixture()
        with TemporaryDirectory() as temporary:
            plan = fixture.plan(Path(temporary)).model_copy(
                update={
                    "event_windows": [
                        SourceEventWindow(
                            start=fixture.cutoff - timedelta(days=1),
                            end=fixture.cutoff,
                            events=["example' OR true --"],
                            properties=[SourcePropertyFilter(name="unsafe`key", values=["value' OR true --"])],
                        )
                    ]
                }
            )
            query = SourceEvents(self.api(fixture), plan).predicate()
            assert "'example\\' OR true --'" in query
            assert "properties.`unsafe``key`" in query
            assert "'value\\' OR true --'" in query

    @parameterized.expand([("https://elsewhere.example.com/api/projects/12/events/",), ("/api/projects/13/events/",)])
    def test_api_refuses_cross_origin_or_cross_project_pagination(self, path: str) -> None:
        fixture = SourceFixture()
        with self.assertRaisesRegex(SourceExportError, "leave"):
            self.api(fixture).read(path)
        assert fixture.requests == []

    def test_timestamp_pagination_keeps_boundary_ties_and_refuses_unpageable_ties(self) -> None:
        fixture = SourceFixture()
        api = self.api(fixture)
        times = [fixture.cutoff - timedelta(seconds=seconds) for seconds in (1, 2, 2, 3)]

        def rows(request: httpx.Request) -> httpx.Response:
            upper = datetime.fromisoformat(request.url.params["date_to"])
            selected = [
                {"id": str(index), "created_at": date.isoformat()} for index, date in enumerate(times) if date < upper
            ]
            return httpx.Response(200, json=selected[:3])

        api.client.close()
        api.client = httpx.Client(transport=httpx.MockTransport(rows))
        result = api.dated_rows(
            api.project_path + "signals/scout/notes/",
            date_field="created_at",
            identity_field="id",
            start=None,
            end=fixture.cutoff,
            cap=3,
            max_rows=10,
        )
        assert {row["id"] for row in result} == {"0", "1", "2", "3"}
        times = [times[0]] * 4
        with self.assertRaisesRegex(SourceExportError, "share one timestamp"):
            api.dated_rows(
                api.project_path + "signals/scout/notes/",
                date_field="created_at",
                identity_field="id",
                start=None,
                end=fixture.cutoff,
                cap=3,
                max_rows=10,
            )
