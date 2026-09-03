from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework.exceptions import PermissionDenied

from posthog.models import Team

from products.canvas.backend.notebook_integration import CanvasGenerationState, NotebookCanvasVersion
from products.notebooks.backend.models import (
    GeneratedWidget,
    GeneratedWidgetGenerationJob,
    GeneratedWidgetVersion,
    Notebook,
    NotebookNodeRun,
    NotebookWidgetInstance,
)
from products.notebooks.backend.reusable_widgets import (
    list_reusable_widgets,
    read_reusable_widget_demo_frame,
    start_reusable_widget_generation,
)
from products.notebooks.backend.widgets import (
    WidgetConflictError,
    get_widget_status,
    read_widget_frame,
    revert_widget_version,
    set_widget_instance_version,
)


def _markdown_content(markdown: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {"type": "ph-markdown-notebook", "attrs": {"nodeId": "markdown-notebook-v2", "markdown": markdown}}
        ],
    }


class TestReusableWidgets(APIBaseTest):
    node_id = "revenue-chart"
    input_name = "revenue_df"

    def setUp(self) -> None:
        super().setUp()
        self.notebook = Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            content=_markdown_content(
                f'<PythonV2 nodeId="source" code="{self.input_name} = source.copy()" '
                f'returnVariable="{self.input_name}" />\n\n'
                f'<Widget nodeId="{self.node_id}" prompt="Chart revenue by plan" />'
            ),
        )
        self.run = NotebookNodeRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            notebook=self.notebook,
            user=self.user,
            node_id="source",
            node_type=NotebookNodeRun.NodeType.PYTHON,
            code=f"{self.input_name} = source.copy()",
            status=NotebookNodeRun.Status.DONE,
            envelope={
                "types": [["plan", "string"], ["revenue", "float64"]],
                "first_page": [[f"Plan {index}", index * 100] for index in range(30)],
                "row_count": 30,
            },
        )
        self.widget = GeneratedWidget.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            name="Chart revenue by plan",
            canvas_id=uuid4(),
            created_by=self.user,
        )
        self.instance = NotebookWidgetInstance.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            notebook=self.notebook,
            node_id=self.node_id,
            widget=self.widget,
            created_by=self.user,
        )
        self.version = GeneratedWidgetVersion.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            widget=self.widget,
            canvas_source_version_id=uuid4(),
            title="Revenue by plan",
            operation=GeneratedWidgetVersion.Operation.INITIAL,
            prompt_delta="Chart revenue by plan",
            generator_version="4",
            input_contract=[
                {
                    "slot": self.input_name,
                    "sourceName": self.input_name,
                    "columns": [
                        {"name": "plan", "type": "string"},
                        {"name": "revenue", "type": "float64"},
                    ],
                    "schemaHash": "",
                }
            ],
            schema_hash="",
            created_by=self.user,
        )
        self.widget.current_version = self.version
        self.widget.save(update_fields=["current_version"])
        self.instance.pinned_version = self.version
        self.instance.save(update_fields=["pinned_version"])

    def _canvas_version(self) -> NotebookCanvasVersion:
        return NotebookCanvasVersion(
            id=self.version.canvas_source_version_id,
            build_status="ready",
            artifact_url="https://example.com/revenue-widget.html",
            build_hash="a" * 64,
        )

    def _publish(self):
        url = f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/widgets/{self.node_id}/publish/"
        with patch(
            "products.canvas.backend.notebook_integration.list_notebook_canvas_versions",
            return_value=[self._canvas_version()],
        ):
            return self.client.post(
                url,
                data={
                    "name": "Revenue by plan",
                    "description": "Compares revenue across plans.",
                    "tags": ["Revenue", " revenue ", "Plans"],
                },
                format="json",
            )

    def test_publish_saves_demo_data_and_unpins_the_source_instance(self) -> None:
        response = self._publish()

        assert response.status_code == 201
        assert response.json()["name"] == "Revenue by plan"
        assert response.json()["tags"] == ["Revenue", "Plans"]
        self.widget.refresh_from_db()
        self.instance.refresh_from_db()
        self.version.refresh_from_db()
        assert self.widget.publication_status == GeneratedWidget.PublicationStatus.PUBLISHED
        assert self.widget.published_by == self.user
        assert self.instance.pinned_version is None
        assert len(self.version.demo_data[self.input_name]["rows"]) == 20
        assert self.version.demo_data[self.input_name]["runId"] == str(self.run.id)
        assert self.version.demo_data[self.input_name]["truncated"] is True

        frame = read_reusable_widget_demo_frame(
            team_id=self.team.id,
            widget_id=self.widget.id,
            frame_name=self.input_name,
        )
        assert frame.frame["rows"][0] == ["Plan 0", 0]

    def test_catalog_lists_only_published_widgets_for_the_team(self) -> None:
        assert list_reusable_widgets(team_id=self.team.id).count == 0
        self._publish()

        response = self.client.get(f"/api/projects/{self.team.id}/notebook_widgets/?search=revenue")

        assert response.status_code == 200
        assert response.json()["count"] == 1
        assert response.json()["results"][0]["id"] == str(self.widget.id)
        assert response.json()["results"][0]["instance_count"] == 1
        other_team = Team.objects.create(organization=self.organization)
        assert list_reusable_widgets(team_id=other_team.id).count == 0

    def test_catalog_detail_and_demo_frame_use_the_saved_snapshot(self) -> None:
        self._publish()
        with patch(
            "products.canvas.backend.notebook_integration.list_notebook_canvas_versions",
            return_value=[self._canvas_version()],
        ):
            detail = self.client.get(f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/")
        demo = self.client.get(
            f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/frames/{self.input_name}/"
        )

        assert detail.status_code == 200
        assert detail.json()["current_version"]["artifact_url"] == "https://example.com/revenue-widget.html"
        assert detail.json()["current_version"]["has_demo_data"] is True
        assert demo.status_code == 200
        assert len(demo.json()["rows"]) == 20

    def test_notebook_mutation_redirects_after_publication(self) -> None:
        self._publish()
        status = get_widget_status(notebook=self.notebook, node_id=self.node_id)
        assert status.is_reusable is True

        with self.assertRaises(WidgetConflictError) as error:
            revert_widget_version(
                notebook=self.notebook,
                node_id=self.node_id,
                version_id=self.version.id,
                expected_current_version_id=self.version.id,
                user_id=self.user.id,
            )

        assert error.exception.code == "reusable_widget_shared"

    def test_publish_requires_current_frame_access(self) -> None:
        with patch(
            "products.notebooks.backend.presentation.views.notebook.NotebookViewSet._authorize_widget_run",
            side_effect=PermissionDenied,
        ):
            response = self._publish()

        assert response.status_code == 403
        self.widget.refresh_from_db()
        assert self.widget.publication_status == GeneratedWidget.PublicationStatus.PRIVATE

    def test_pin_selects_an_immutable_version_and_unpin_follows_latest(self) -> None:
        self._publish()
        latest = GeneratedWidgetVersion.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            widget=self.widget,
            canvas_source_version_id=uuid4(),
            title="Updated revenue by plan",
            operation=GeneratedWidgetVersion.Operation.IMPROVE,
            prompt_delta="Use a stacked chart",
            generator_version="4",
            input_contract=self.version.input_contract,
            schema_hash="",
            created_by=self.user,
        )
        self.widget.current_version = latest
        self.widget.save(update_fields=["current_version"])
        selected_state = CanvasGenerationState(
            current_source_version_id=self.version.canvas_source_version_id,
            artifact_url="https://example.com/selected.html",
            build_status="ready",
            build_error=None,
            build_hash="b" * 64,
        )
        latest_state = CanvasGenerationState(
            current_source_version_id=latest.canvas_source_version_id,
            artifact_url="https://example.com/latest.html",
            build_status="ready",
            build_error=None,
            build_hash="c" * 64,
        )

        with patch(
            "products.canvas.backend.notebook_integration.get_canvas_generation_state",
            return_value=selected_state,
        ):
            pinned = set_widget_instance_version(
                notebook=self.notebook,
                node_id=self.node_id,
                version_id=self.version.id,
            )
        with patch(
            "products.canvas.backend.notebook_integration.get_canvas_generation_state",
            return_value=latest_state,
        ):
            unpinned = set_widget_instance_version(notebook=self.notebook, node_id=self.node_id, version_id=None)

        assert pinned.current_version_id == self.version.id
        assert pinned.pinned_version_id == self.version.id
        assert unpinned.current_version_id == latest.id
        assert unpinned.pinned_version_id is None

    def test_attach_remaps_a_contract_slot_to_a_local_dataframe(self) -> None:
        self._publish()
        notebook = Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            content=_markdown_content(
                '<PythonV2 nodeId="other-source" code="other_df = source.copy()" returnVariable="other_df" />\n\n'
                f'<Widget nodeId="copy" id="{self.widget.id}" />'
            ),
        )
        NotebookNodeRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            notebook=notebook,
            user=self.user,
            node_id="other-source",
            node_type=NotebookNodeRun.NodeType.PYTHON,
            code="other_df = source.copy()",
            status=NotebookNodeRun.Status.DONE,
            envelope={
                "types": [["segment", "string"], ["amount", "float64"]],
                "first_page": [["Enterprise", 500]],
                "row_count": 1,
            },
        )
        state = CanvasGenerationState(
            current_source_version_id=self.version.canvas_source_version_id,
            artifact_url="https://example.com/widget.html",
            build_status="ready",
            build_error=None,
            build_hash="d" * 64,
        )
        url = f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/widgets/copy/attach/"
        with patch(
            "products.canvas.backend.notebook_integration.get_canvas_generation_state",
            return_value=state,
        ):
            response = self.client.post(
                url,
                data={
                    "widget_id": str(self.widget.id),
                    "version_id": None,
                    "input_bindings": {
                        self.input_name: {"source": "other_df", "hog": "return rows"},
                    },
                },
                format="json",
            )

        assert response.status_code == 200
        assert response.json()["is_reusable"] is True
        assert response.json()["input_bindings"][self.input_name]["source"] == "other_df"
        instance = NotebookWidgetInstance.objects.for_team(self.team.id).get(notebook=notebook, node_id="copy")
        assert instance.pinned_version is None
        assert instance.input_bindings[self.input_name]["hog"] == "return rows"
        frame = read_widget_frame(
            notebook=notebook,
            node_id="copy",
            frame_name=self.input_name,
            authorize_run=lambda _run: None,
            user=self.user,
        )
        assert frame.frame["rows"] == [["Enterprise", 500]]

    def test_shared_edit_queues_a_global_version_without_pinning_the_source(self) -> None:
        self._publish()
        state = CanvasGenerationState(
            current_source_version_id=self.version.canvas_source_version_id,
            artifact_url="https://example.com/widget.html",
            build_status="ready",
            build_error=None,
            build_hash="e" * 64,
        )
        generation_id = uuid4()
        with (
            patch("products.notebooks.backend.widgets._is_ai_usage_limited", return_value=False),
            patch("products.notebooks.backend.widgets.start_widget_generation_workflow") as start_workflow,
            patch(
                "products.canvas.backend.notebook_integration.get_canvas_generation_state",
                return_value=state,
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            status = start_reusable_widget_generation(
                team_id=self.team.id,
                widget_id=self.widget.id,
                prompt="Use a stacked bar chart",
                model="claude-sonnet-4-6",
                generation_id=generation_id,
                operation=GeneratedWidgetVersion.Operation.IMPROVE,
                expected_current_version_id=self.version.id,
                user_id=self.user.id,
            )

        job = GeneratedWidgetGenerationJob.objects.for_team(self.team.id).get(idempotency_key=generation_id)
        self.instance.refresh_from_db()
        assert status.active_job is not None
        assert job.input_contract == self.version.input_contract
        assert self.instance.pinned_version is None
        start_workflow.assert_called_once()

    def test_fork_replaces_the_placement_with_an_independent_private_widget(self) -> None:
        self._publish()
        forked_canvas_id = uuid4()
        forked_source_version_id = uuid4()
        state = CanvasGenerationState(
            current_source_version_id=forked_source_version_id,
            artifact_url="https://example.com/forked-widget.html",
            build_status="ready",
            build_error=None,
            build_hash="f" * 64,
        )
        url = f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/widgets/{self.node_id}/fork/"
        with (
            patch(
                "products.canvas.backend.notebook_integration.get_notebook_canvas_source",
                return_value="export default function Widget() { return null }",
            ),
            patch("products.tasks.backend.facade.api.ensure_personal_channel_id", return_value=uuid4()),
            patch(
                "products.canvas.backend.notebook_integration.create_notebook_canvas",
                return_value=forked_canvas_id,
            ),
            patch(
                "products.canvas.backend.notebook_integration.prepare_notebook_canvas_source",
                return_value=object(),
            ),
            patch(
                "products.canvas.backend.notebook_integration.publish_prepared_notebook_canvas_source",
                return_value=forked_source_version_id,
            ),
            patch(
                "products.canvas.backend.notebook_integration.get_canvas_generation_state",
                return_value=state,
            ),
        ):
            response = self.client.post(url)

        assert response.status_code == 201
        assert response.json()["is_reusable"] is False
        self.instance.refresh_from_db()
        assert self.instance.widget_id != self.widget.id
        assert self.instance.widget.publication_status == GeneratedWidget.PublicationStatus.PRIVATE
        assert self.instance.widget.canvas_id == forked_canvas_id
        assert self.instance.pinned_version_id == self.instance.widget.current_version_id
        assert self.instance.widget.current_version is not None
        assert self.instance.widget.current_version.canvas_source_version_id == forked_source_version_id
