from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.canvas.backend.facade.notebooks import CanvasGenerationState, NotebookCanvasSource
from products.canvas.backend.models import Canvas, CanvasSourceVersion
from products.notebooks.backend.genui import (
    GENUI_GENERATOR_VERSION,
    GenUIError,
    GenUIInputInspection,
    GenUIRateLimitError,
    _apply_current_state,
    _assert_generation_allowed,
    _start_generation,
    cleanup_removed_genui_nodes,
    ensure_genui,
    generation_hash,
    inspect_inputs,
    normalize_inputs,
    read_genui_frame,
    reconcile_generation,
    restore_genui_version,
    run_stale_genui,
)
from products.notebooks.backend.genui_generation import _generation_prompt, generate_genui_source
from products.notebooks.backend.genui_snapshot_store import GenUISnapshotStoreError, build_snapshot_key, read_snapshot
from products.notebooks.backend.models import Notebook, NotebookGenUI, NotebookNodeRun
from products.tasks.backend.models import Channel


def markdown_content(markdown: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "ph-markdown-notebook", "attrs": {"nodeId": "markdown-notebook-v2", "markdown": markdown}}
        ],
    }


class TestGenUIInputValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("normalizes", [" locations_df ", "users_df"], ["locations_df", "users_df"], None),
            ("duplicate", ["events_df", "events_df"], None, "duplicate_input_name"),
            ("invalid", ["events-df"], None, "invalid_input_name"),
            ("too_many", ["a", "b", "c", "d", "e"], None, "too_many_inputs"),
        ]
    )
    def test_normalize_inputs(
        self, _name: str, raw: list[str], expected: list[str] | None, error_code: str | None
    ) -> None:
        if error_code is None:
            assert normalize_inputs(raw) == expected
            return
        with self.assertRaises(GenUIError) as error:
            normalize_inputs(raw)
        assert error.exception.code == error_code

    def test_snapshot_keys_enforce_the_team_boundary(self) -> None:
        key = build_snapshot_key(team_id=42, notebook_id=self._uuid(), node_id="globe", snapshot_hash="a" * 64)
        assert key.startswith("notebooks/genui/team_42/")
        with self.assertRaises(GenUISnapshotStoreError):
            read_snapshot(key=key, team_id=43)

    def test_generation_prompt_contains_schema_but_not_dataframe_values(self) -> None:
        prompt = _generation_prompt(
            prompt="Render a globe",
            schemas=[{"name": "locations_df", "columns": [{"name": "lat", "type": "float64"}]}],
            input_names=["locations_df"],
        )

        assert "locations_df" in prompt
        assert '"lat"' in prompt
        assert "51.5" not in prompt
        assert "mcp__posthog__exec" not in prompt
        assert "single string field named `source`" in prompt

    def test_source_generation_repairs_invalid_code_once(self) -> None:
        client = MagicMock()
        client.with_options.return_value = client
        client.chat.completions.create.side_effect = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"source":"import chart from \\"unsupported-chart\\"; export default function Canvas() { return <div /> }"}'
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"source":"export default function Canvas() { return <div>Ready</div> }"}'
                        )
                    )
                ]
            ),
        ]

        source = generate_genui_source(
            team_id=42,
            trace_id="00000000-0000-0000-0000-000000000042",
            prompt="Render a globe",
            schemas=[{"name": "locations_df", "columns": [{"name": "lat", "type": "float64"}]}],
            input_names=["locations_df"],
            current_source=None,
            build_diagnostics=[],
            client=client,
        )

        assert source == "export default function Canvas() { return <div>Ready</div> }"
        assert client.chat.completions.create.call_count == 2
        repair_prompt = client.chat.completions.create.call_args_list[1].kwargs["messages"][1]["content"]
        assert "import_not_allowed" in repair_prompt

    @staticmethod
    def _uuid() -> UUID:
        return UUID("00000000-0000-0000-0000-000000000042")


class TestGenUILifecycle(APIBaseTest):
    NODE_ID = "globe"
    INPUT_NAME = "locations_df"
    CODE = "locations_df = points.copy()"

    def _notebook(self, *, team: Team | None = None, include_genui: bool = True) -> Notebook:
        genui = (
            f'\n\n<GenUI nodeId="{self.NODE_ID}" prompt="Render a globe" inputs="{self.INPUT_NAME}" />'
            if include_genui
            else ""
        )
        return Notebook.objects.create(
            team=team or self.team,
            created_by=self.user,
            content=markdown_content(
                f'<PythonV2 nodeId="source" code="{self.CODE}" returnVariable="{self.INPUT_NAME}" />{genui}'
            ),
        )

    def _run(
        self, notebook: Notebook, *, columns: list[list[str]] | None = None, rows: list[list[object]] | None = None
    ):
        if rows is None:
            rows = [[51.5, -0.1]]
        return NotebookNodeRun.objects.for_team(notebook.team_id).create(
            team_id=notebook.team_id,
            notebook=notebook,
            user=self.user,
            node_id="source",
            node_type=NotebookNodeRun.NodeType.PYTHON,
            code=self.CODE,
            status=NotebookNodeRun.Status.DONE,
            envelope={
                "types": columns or [["lat", "float64"], ["lng", "float64"]],
                "first_page": rows,
                "row_count": len(rows),
            },
        )

    def _ready_row(self, notebook: Notebook) -> tuple[NotebookGenUI, GenUIInputInspection]:
        inspection = inspect_inputs(notebook, [self.INPUT_NAME])
        desired_hash = generation_hash(prompt="Render a globe", inputs=[self.INPUT_NAME], inspection=inspection)
        row = NotebookGenUI.objects.for_team(notebook.team_id).create(
            team_id=notebook.team_id,
            notebook=notebook,
            node_id=self.NODE_ID,
            prompt="Render a globe",
            inputs=[self.INPUT_NAME],
            generator_version=GENUI_GENERATOR_VERSION,
            generation_hash=desired_hash,
            generated_hash=desired_hash,
            generated_schema_hash=inspection.schema_hash,
            lifecycle_status=NotebookGenUI.LifecycleStatus.READY,
            canvas_id=UUID("00000000-0000-0000-0000-000000000100"),
            source_version_id=UUID("00000000-0000-0000-0000-000000000101"),
            build_id=UUID("00000000-0000-0000-0000-000000000102"),
            snapshot_object_key=f"notebooks/genui/team_{notebook.team_id}/old.json",
            snapshot_hash=inspection.snapshot_hash,
            snapshot_metadata=inspection.snapshot_metadata,
        )
        return row, inspection

    @staticmethod
    def _canvas_state(row: NotebookGenUI) -> CanvasGenerationState:
        assert row.canvas_id is not None
        return CanvasGenerationState(
            canvas_id=row.canvas_id,
            current_source_version_id=row.source_version_id,
            published_build_id=row.build_id,
            published_source_version_id=row.source_version_id,
            published_artifact_url="https://example.com/globe.html",
            published_source_size=100,
            published_artifact_size=200,
            current_build_id=row.build_id,
            current_build_status="ready",
            current_build_diagnostics=[],
        )

    def test_input_inspection_reports_missing_never_run_failed_and_ready(self) -> None:
        notebook = self._notebook()
        assert inspect_inputs(notebook, [self.INPUT_NAME]).states[0]["input_status"] == "never_run"
        assert inspect_inputs(notebook, ["missing_df"]).states[0]["input_status"] == "missing"
        run = NotebookNodeRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            notebook=notebook,
            user=self.user,
            node_id="source",
            node_type=NotebookNodeRun.NodeType.PYTHON,
            code=self.CODE,
            status=NotebookNodeRun.Status.FAILED,
            error="Execution failed",
        )
        assert inspect_inputs(notebook, [self.INPUT_NAME]).states[0]["input_status"] == "failed"
        run.delete()
        self._run(notebook)
        assert inspect_inputs(notebook, [self.INPUT_NAME]).states[0]["input_status"] == "ready"

    def test_input_snapshot_is_bounded_and_marks_truncation(self) -> None:
        notebook = self._notebook()
        self._run(notebook, rows=[[index, "x" * 5_000] for index in range(101)])

        inspection = inspect_inputs(notebook, [self.INPUT_NAME])
        frame = inspection.frames[self.INPUT_NAME]

        assert isinstance(frame, dict)
        assert frame["includedRowCount"] == 100
        assert frame["totalRowCount"] == 101
        assert frame["truncated"] is True
        assert isinstance(frame["rows"], list)
        first_row = frame["rows"][0]
        assert isinstance(first_row, list)
        assert len(first_row[1]) == 4_096

    @patch("products.notebooks.backend.genui.process_genui_generation.delay")
    @patch("products.notebooks.backend.genui.canvas_facade.create_notebook_canvas")
    @patch("products.notebooks.backend.genui.tasks_facade.ensure_personal_channel_id")
    def test_generation_queues_one_direct_source_job(
        self, ensure_personal_channel_id, create_notebook_canvas, queue_generation
    ) -> None:
        notebook = Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            content=markdown_content(f'<GenUI nodeId="{self.NODE_ID}" prompt="Animate" />'),
        )
        inspection = inspect_inputs(notebook, [])
        row = NotebookGenUI.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            notebook=notebook,
            node_id=self.NODE_ID,
            prompt="Animate",
            inputs=[],
            generator_version=GENUI_GENERATOR_VERSION,
            generation_hash="a" * 64,
            pending_generation_hash="a" * 64,
            lifecycle_status=NotebookGenUI.LifecycleStatus.GENERATING,
        )
        channel_id = UUID("00000000-0000-0000-0000-000000000200")
        canvas_id = UUID("00000000-0000-0000-0000-000000000201")
        ensure_personal_channel_id.return_value = channel_id
        create_notebook_canvas.return_value = canvas_id

        started = _start_generation(row=row, notebook=notebook, user_id=self.user.id, inspection=inspection)

        assert started.canvas_id == canvas_id
        create_notebook_canvas.assert_called_once_with(
            team_id=self.team.id,
            user_id=self.user.id,
            channel_id=channel_id,
            name="Animate",
            context="Animate",
        )
        queue_generation.assert_called_once_with(self.team.id, str(row.id), self.user.id, "a" * 64)

    @patch("products.notebooks.backend.genui._run_claimed_generation")
    @patch("products.notebooks.backend.genui._assert_generation_allowed")
    @patch("products.notebooks.backend.genui._store_snapshot", return_value=("snapshot.json", {}))
    def test_ensure_is_idempotent_while_generation_is_claimed(
        self, _store_snapshot, _assert_generation_allowed, run_claimed_generation
    ) -> None:
        notebook = Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            content=markdown_content(f'<GenUI nodeId="{self.NODE_ID}" prompt="Animate" />'),
        )
        run_claimed_generation.side_effect = lambda **kwargs: kwargs["row"]

        first, _ = ensure_genui(
            notebook=notebook,
            node_id=self.NODE_ID,
            prompt="Animate",
            inputs=[],
            user_id=self.user.id,
            can_generate=True,
        )
        second, _ = ensure_genui(
            notebook=notebook,
            node_id=self.NODE_ID,
            prompt="Animate",
            inputs=[],
            user_id=self.user.id,
            can_generate=True,
        )

        assert first.id == second.id
        assert NotebookGenUI.objects.for_team(self.team.id).filter(notebook=notebook).count() == 1
        _store_snapshot.assert_called_once()
        run_claimed_generation.assert_called_once()

    @patch("products.notebooks.backend.genui._is_ai_usage_limited", return_value=True)
    def test_generation_stops_when_ai_usage_is_limited(self, _usage_limit_reached) -> None:
        notebook = self._notebook()

        with self.assertRaises(GenUIRateLimitError) as error:
            _assert_generation_allowed(notebook=notebook, user_id=self.user.id)

        assert error.exception.code == "usage_limit_exceeded"

    @patch("products.notebooks.backend.genui.capture_genui_lifecycle")
    @patch("products.notebooks.backend.genui.delete_snapshot")
    @patch("products.notebooks.backend.genui._store_snapshot", return_value=("new-snapshot.json", {"size": 10}))
    @patch("products.notebooks.backend.genui.canvas_facade.get_canvas_generation_state")
    def test_run_reuses_source_for_new_rows(
        self, get_canvas_state, _store_snapshot, delete_snapshot, _capture_genui_lifecycle
    ) -> None:
        notebook = self._notebook()
        self._run(notebook)
        row, _ = self._ready_row(notebook)
        get_canvas_state.return_value = self._canvas_state(row)
        source_version_id = row.source_version_id
        self._run(notebook, rows=[[40.7, -74.0], [37.8, -122.4]])

        with self.captureOnCommitCallbacks(execute=True):
            refreshed, inspection = run_stale_genui(notebook=notebook, node_id=self.NODE_ID)

        assert refreshed.lifecycle_status == NotebookGenUI.LifecycleStatus.READY
        assert refreshed.source_version_id == source_version_id
        assert refreshed.snapshot_hash == inspection.snapshot_hash
        assert refreshed.snapshot_object_key == "new-snapshot.json"
        delete_snapshot.assert_called_once()

    @patch("products.notebooks.backend.genui.canvas_facade.get_canvas_generation_state")
    def test_schema_change_requires_regeneration(self, get_canvas_state) -> None:
        notebook = self._notebook()
        self._run(notebook)
        row, _ = self._ready_row(notebook)
        get_canvas_state.return_value = self._canvas_state(row)
        self._run(notebook, columns=[["latitude", "float64"], ["lng", "float64"]])

        inspection = inspect_inputs(notebook, [self.INPUT_NAME])
        row.generation_hash = generation_hash(prompt=row.prompt, inputs=[self.INPUT_NAME], inspection=inspection)
        row.save(update_fields=["generation_hash", "updated_at"])
        refreshed = reconcile_generation(row, inspection)
        refreshed = _apply_current_state(
            row=refreshed,
            inspection=inspection,
            promote_snapshot=False,
        )
        assert refreshed.lifecycle_status == NotebookGenUI.LifecycleStatus.INCOMPATIBLE

    @patch("products.notebooks.backend.genui.capture_genui_lifecycle")
    @patch("products.notebooks.backend.genui.canvas_facade.get_canvas_generation_state")
    def test_failed_replacement_keeps_the_last_good_artifact(self, get_canvas_state, _capture_genui_lifecycle) -> None:
        notebook = self._notebook()
        self._run(notebook)
        row, inspection = self._ready_row(notebook)
        row.pending_generation_hash = "b" * 64
        row.lifecycle_status = NotebookGenUI.LifecycleStatus.BUILDING
        row.save()
        assert row.canvas_id is not None
        get_canvas_state.return_value = CanvasGenerationState(
            canvas_id=row.canvas_id,
            current_source_version_id=UUID("00000000-0000-0000-0000-000000000103"),
            published_build_id=row.build_id,
            published_source_version_id=row.source_version_id,
            published_artifact_url="https://example.com/last-good.html",
            published_source_size=100,
            published_artifact_size=200,
            current_build_id=UUID("00000000-0000-0000-0000-000000000104"),
            current_build_status="failed",
            current_build_diagnostics=[{"severity": "error", "message": "Build failed"}],
        )

        failed = reconcile_generation(row, inspection)

        assert failed.lifecycle_status == NotebookGenUI.LifecycleStatus.FAILED
        assert failed.source_version_id == row.source_version_id
        assert failed.build_id == row.build_id

    @patch("products.notebooks.backend.genui.capture_genui_lifecycle")
    @patch("products.notebooks.backend.genui.canvas_facade.get_canvas_generation_state")
    def test_generation_timeout_becomes_a_retryable_failure(self, get_canvas_state, _capture_genui_lifecycle) -> None:
        notebook = self._notebook()
        self._run(notebook)
        row, inspection = self._ready_row(notebook)
        row.pending_generation_hash = "b" * 64
        row.lifecycle_status = NotebookGenUI.LifecycleStatus.GENERATING
        row.generation_started_at = timezone.now() - timedelta(minutes=31)
        row.save()
        get_canvas_state.return_value = self._canvas_state(row)

        failed = reconcile_generation(row, inspection)

        assert failed.lifecycle_status == NotebookGenUI.LifecycleStatus.FAILED
        assert failed.last_error_code == "generation_timeout"

    @patch("products.notebooks.backend.genui._store_snapshot")
    @patch("products.notebooks.backend.genui.canvas_facade.get_canvas_generation_state")
    def test_definition_change_keeps_the_in_flight_snapshot(self, get_canvas_state, store_snapshot) -> None:
        notebook = self._notebook()
        self._run(notebook)
        row, inspection = self._ready_row(notebook)
        row.pending_generation_hash = row.generation_hash
        row.pending_schema_hash = inspection.schema_hash
        row.pending_snapshot_object_key = "in-flight.json"
        row.pending_snapshot_hash = inspection.snapshot_hash
        row.lifecycle_status = NotebookGenUI.LifecycleStatus.GENERATING
        row.generation_started_at = timezone.now()
        row.save()
        get_canvas_state.return_value = self._canvas_state(row)
        self._run(notebook, rows=[[40.7, -74.0]])

        updated, _ = ensure_genui(
            notebook=notebook,
            node_id=self.NODE_ID,
            prompt="Render another globe",
            inputs=[self.INPUT_NAME],
            user_id=self.user.id,
            can_generate=False,
        )

        assert updated.pending_snapshot_object_key == "in-flight.json"
        assert updated.pending_snapshot_hash == inspection.snapshot_hash
        assert updated.generation_hash != updated.pending_generation_hash
        store_snapshot.assert_not_called()

    @patch("products.notebooks.backend.genui.capture_genui_lifecycle")
    @patch("products.notebooks.backend.genui.canvas_facade.get_canvas_generation_state")
    def test_prompt_only_regeneration_keeps_the_active_snapshot(
        self, get_canvas_state, _capture_genui_lifecycle
    ) -> None:
        notebook = self._notebook()
        self._run(notebook)
        row, inspection = self._ready_row(notebook)
        previous_snapshot_key = row.snapshot_object_key
        row.generation_hash = "b" * 64
        row.pending_generation_hash = "b" * 64
        row.pending_schema_hash = inspection.schema_hash
        row.lifecycle_status = NotebookGenUI.LifecycleStatus.BUILDING
        row.save()
        new_source_id = UUID("00000000-0000-0000-0000-000000000103")
        assert row.canvas_id is not None
        get_canvas_state.return_value = CanvasGenerationState(
            canvas_id=row.canvas_id,
            current_source_version_id=new_source_id,
            published_build_id=UUID("00000000-0000-0000-0000-000000000104"),
            published_source_version_id=new_source_id,
            published_artifact_url="https://example.com/new.html",
            published_source_size=110,
            published_artifact_size=220,
            current_build_id=UUID("00000000-0000-0000-0000-000000000104"),
            current_build_status="ready",
            current_build_diagnostics=[],
        )

        regenerated = reconcile_generation(row, inspection)

        assert regenerated.lifecycle_status == NotebookGenUI.LifecycleStatus.READY
        assert regenerated.snapshot_object_key == previous_snapshot_key

    @patch("products.notebooks.backend.genui.read_snapshot")
    def test_frame_reads_are_declared_and_notebook_scoped(self, read_snapshot_mock) -> None:
        notebook = self._notebook()
        self._run(notebook)
        self._ready_row(notebook)
        frame = {
            "name": self.INPUT_NAME,
            "columns": [{"name": "lat", "type": "float64"}],
            "rows": [[51.5]],
            "totalRowCount": 1,
            "includedRowCount": 1,
            "truncated": False,
        }
        read_snapshot_mock.return_value = {self.INPUT_NAME: frame}

        assert read_genui_frame(notebook=notebook, node_id=self.NODE_ID, frame_name=self.INPUT_NAME) == frame
        with self.assertRaises(GenUIError) as error:
            read_genui_frame(notebook=notebook, node_id=self.NODE_ID, frame_name="private_df")
        assert error.exception.code == "frame_not_allowed"

        response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/genui/{self.NODE_ID}/frames/private_df/"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["code"] == "frame_not_allowed"

    @patch("products.notebooks.backend.genui.canvas_facade.get_canvas_generation_state")
    def test_status_returns_one_notebook_contract_without_canvas_channels(self, get_canvas_state) -> None:
        notebook = self._notebook()
        self._run(notebook)
        row, _ = self._ready_row(notebook)
        get_canvas_state.return_value = self._canvas_state(row)

        response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/genui/{self.NODE_ID}/status/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["artifact_url"] == "https://example.com/globe.html"
        assert "channel_id" not in response.json()
        assert "canvas_id" not in response.json()

    @patch("products.notebooks.backend.genui.canvas_facade.get_notebook_canvas_source")
    def test_source_endpoint_returns_the_current_generated_component(self, get_canvas_source) -> None:
        notebook = self._notebook()
        self._run(notebook)
        row, _ = self._ready_row(notebook)
        assert row.source_version_id is not None
        get_canvas_source.return_value = NotebookCanvasSource(
            version_id=row.source_version_id,
            source="export default function Canvas() { return <div>Hello</div> }",
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/genui/{self.NODE_ID}/source/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "version_id": str(row.source_version_id),
            "source": "export default function Canvas() { return <div>Hello</div> }",
        }

    def test_versions_endpoint_marks_the_live_notebook_version(self) -> None:
        notebook = self._notebook()
        self._run(notebook)
        row, _ = self._ready_row(notebook)
        with team_scope(self.team.id):
            channel = Channel.objects.create(team=self.team, name="Notebook visualizations")
            canvas = Canvas.objects.create(team=self.team, channel=channel, name="Globe", created_by=self.user)
            previous_version = CanvasSourceVersion.objects.create(
                team=self.team,
                canvas=canvas,
                source_hash="1" * 64,
                source_object_key="canvas_source/previous",
                source_size=10,
                prompt="First globe",
            )
            current_version = CanvasSourceVersion.objects.create(
                team=self.team,
                canvas=canvas,
                parent_version=previous_version,
                source_hash="2" * 64,
                source_object_key="canvas_source/current",
                source_size=10,
                prompt="Current globe",
            )
        row.canvas_id = canvas.id
        row.source_version_id = current_version.id
        row.save(update_fields=["canvas_id", "source_version_id", "updated_at"])

        response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/genui/{self.NODE_ID}/versions/"
        )

        assert response.status_code == status.HTTP_200_OK
        versions = response.json()["results"]
        assert [version["id"] for version in versions] == [str(current_version.id), str(previous_version.id)]
        assert [version["is_current"] for version in versions] == [True, False]

    @patch("products.notebooks.backend.genui.canvas_facade.restore_notebook_canvas_version")
    @patch("products.notebooks.backend.genui.canvas_facade.get_canvas_generation_state")
    def test_restoring_a_version_keeps_the_live_artifact_until_its_build_is_ready(
        self, get_canvas_state, restore_canvas_version
    ) -> None:
        notebook = self._notebook()
        self._run(notebook)
        row, _ = self._ready_row(notebook)
        get_canvas_state.return_value = self._canvas_state(row)
        previous_version_id = UUID("00000000-0000-0000-0000-000000000099")
        current_version_id = row.source_version_id

        restored, _ = restore_genui_version(
            notebook=notebook,
            node_id=self.NODE_ID,
            version_id=previous_version_id,
            user_id=self.user.id,
        )

        assert restored.lifecycle_status == NotebookGenUI.LifecycleStatus.BUILDING
        assert restored.source_version_id == current_version_id
        assert restored.pending_generation_hash == restored.generated_hash
        restore_canvas_version.assert_called_once_with(
            team_id=self.team.id,
            canvas_id=row.canvas_id,
            version_id=previous_version_id,
            expected_current_version_id=current_version_id,
            user_id=self.user.id,
        )

    @patch("products.notebooks.backend.genui.canvas_facade.soft_delete_notebook_canvas")
    @patch("products.notebooks.backend.genui.delete_snapshot")
    def test_removed_nodes_clean_up_snapshots_and_canvas(self, delete_snapshot, soft_delete_canvas) -> None:
        notebook = self._notebook(include_genui=False)
        self._run(notebook)
        row, _ = self._ready_row(notebook)

        with self.captureOnCommitCallbacks(execute=True):
            cleanup_removed_genui_nodes(notebook)

        assert not NotebookGenUI.objects.for_team(self.team.id).filter(id=row.id).exists()
        delete_snapshot.assert_called_once_with(key=row.snapshot_object_key, team_id=self.team.id)
        soft_delete_canvas.assert_called_once_with(team_id=self.team.id, canvas_id=row.canvas_id)

    @patch("products.notebooks.backend.genui.canvas_facade.soft_delete_notebook_canvas")
    @patch("products.notebooks.backend.genui.delete_snapshot")
    def test_missing_markdown_does_not_delete_genui_state(self, delete_snapshot, soft_delete_canvas) -> None:
        notebook = self._notebook()
        self._run(notebook)
        row, _ = self._ready_row(notebook)
        notebook.content = {}

        cleanup_removed_genui_nodes(notebook)

        assert NotebookGenUI.objects.for_team(self.team.id).filter(id=row.id).exists()
        delete_snapshot.assert_not_called()
        soft_delete_canvas.assert_not_called()

    @patch("products.notebooks.backend.genui.canvas_facade.soft_delete_notebook_canvas")
    @patch("products.notebooks.backend.genui.delete_snapshot")
    def test_hard_notebook_deletion_cleans_up_before_cascade(self, delete_snapshot, soft_delete_canvas) -> None:
        notebook = self._notebook()
        self._run(notebook)
        row, _ = self._ready_row(notebook)

        with self.captureOnCommitCallbacks(execute=True):
            notebook.delete()

        delete_snapshot.assert_called_once_with(key=row.snapshot_object_key, team_id=self.team.id)
        soft_delete_canvas.assert_called_once_with(team_id=self.team.id, canvas_id=row.canvas_id)

    @parameterized.expand(
        [
            ("ensure", "post", "ensure"),
            ("status", "get", "status"),
            ("run", "post", "run"),
            ("regenerate", "post", "regenerate"),
            ("retry", "post", "retry"),
            ("frame", "get", f"frames/{INPUT_NAME}"),
            ("source", "get", "source"),
            ("versions", "get", "versions"),
            ("restore_version", "post", "versions/restore"),
        ]
    )
    def test_every_endpoint_rejects_a_notebook_from_another_team(self, _name: str, method: str, suffix: str) -> None:
        other_team = Team.objects.create(organization=self.organization, name=f"Other team {_name}")
        other_notebook = self._notebook(team=other_team)
        url = f"/api/projects/{self.team.id}/notebooks/{other_notebook.short_id}/genui/{self.NODE_ID}/{suffix}/"
        request = getattr(self.client, method)

        response = request(url, {"prompt": "Render a globe", "inputs": [self.INPUT_NAME]}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
