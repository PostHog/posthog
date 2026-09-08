import json
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import PermissionDenied

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
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
    reusable_widget_catalog_context,
    start_reusable_widget_generation,
)
from products.notebooks.backend.widget_generation import (
    WIDGET_SECURITY_REVIEW_MODEL,
    GeneratedWidgetSource,
    WidgetSecurityReview,
)
from products.notebooks.backend.widgets import (
    WidgetConflictError,
    WidgetError,
    get_widget_status,
    list_widget_versions,
    read_widget_frame,
    revert_widget_version,
    run_widget_generation_job,
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
        self.node_run = NotebookNodeRun.objects.for_team(self.team.id).create(
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

    @parameterized.expand([("published", False), ("draft", True)])
    def test_source_reads_the_requested_version_without_publishing_the_draft(
        self, _name: str, request_draft: bool
    ) -> None:
        draft = GeneratedWidgetVersion.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            widget=self.widget,
            canvas_source_version_id=uuid4(),
            parent_version=self.version,
            operation=GeneratedWidgetVersion.Operation.IMPROVE,
        )
        self.widget.pending_version = draft
        self.widget.publication_status = GeneratedWidget.PublicationStatus.PUBLISHED
        self.widget.published_at = timezone.now()
        self.widget.save(update_fields=["pending_version", "publication_status", "published_at"])

        source = "export default function Widget() { return <div>Preview</div> }"
        with patch(
            "products.canvas.backend.notebook_integration.get_notebook_canvas_source", return_value=source
        ) as read_source:
            response = self.client.get(
                f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/source/",
                {"version_id": str(draft.id)} if request_draft else {},
            )

        assert response.status_code == 200, response.json()
        assert response.json()["source"] == source
        read_source.assert_called_once_with(
            team_id=self.team.id,
            canvas_id=self.widget.canvas_id,
            version_id=(draft if request_draft else self.version).canvas_source_version_id,
            allow_draft=request_draft,
        )
        self.widget.refresh_from_db()
        assert self.widget.current_version_id == self.version.id
        assert self.widget.pending_version_id == draft.id

    @parameterized.expand([("direct", False), ("mapped_fork", True)])
    def test_publish_saves_demo_data_and_unpins_the_source_instance(self, _name: str, mapped: bool) -> None:
        if mapped:
            self.node_run.envelope["types"] = [["tier", "string"], ["amount", "float64"]]
            self.node_run.save(update_fields=["envelope"])
            self.instance.input_bindings = {
                self.input_name: {
                    "source": self.input_name,
                    "hog": "return arrayMap(row -> {'plan': row.tier, 'revenue': row.amount / 100}, rows)",
                }
            }
            self.instance.save(update_fields=["input_bindings"])
        bindings = self.instance.input_bindings
        response = self._publish()

        assert response.status_code == 201, response.json()
        assert response.json()["name"] == "Revenue by plan"
        assert response.json()["tags"] == ["Revenue", "Plans"]
        self.widget.refresh_from_db()
        self.instance.refresh_from_db()
        self.version.refresh_from_db()
        assert self.widget.publication_status == GeneratedWidget.PublicationStatus.PUBLISHED
        assert self.widget.published_by == self.user
        assert self.instance.pinned_version is None
        assert len(self.version.demo_data[self.input_name]["rows"]) == 20
        assert self.version.demo_data[self.input_name]["runId"] == str(self.node_run.id)
        assert self.version.demo_data[self.input_name]["truncated"] is True

        frame = read_reusable_widget_demo_frame(
            team_id=self.team.id,
            widget_id=self.widget.id,
            frame_name=self.input_name,
        )
        rows = frame.frame["rows"]
        assert isinstance(rows, list)
        assert rows[1] == ["Plan 1", 1 if mapped else 100]
        assert frame.frame["columns"] == self.version.input_contract[0]["columns"]
        if mapped:
            assert self.instance.input_bindings == bindings

    @parameterized.expand([("published", False), ("draft", True)])
    def test_demo_edits_update_only_the_selected_preview(self, _name: str, edit_draft: bool) -> None:
        self._publish()
        self.version.refresh_from_db()
        original_demo = self.version.demo_data
        draft = GeneratedWidgetVersion.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            widget=self.widget,
            canvas_source_version_id=uuid4(),
            input_contract=self.version.input_contract,
            demo_data=original_demo,
            created_by=self.user,
        )
        self.widget.pending_version = draft
        self.widget.save(update_fields=["pending_version"])
        selected = draft if edit_draft else self.version
        untouched = self.version if edit_draft else draft
        original_source = selected.canvas_source_version_id
        rows = [["Starter", 250], ["Growth", 900]]
        response = self.client.post(
            f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/demo-data/",
            data={"version_id": str(selected.id), "frame_name": self.input_name, "rows": rows},
            format="json",
        )
        assert response.status_code == 200, response.json()
        frame = response.json()
        assert frame["rows"] == rows
        assert frame["columns"] == self.version.input_contract[0]["columns"]
        assert frame["includedRowCount"] == frame["totalRowCount"] == 2
        assert frame["truncated"] is False
        saved = self.client.get(
            f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/frames/{self.input_name}/?version_id={selected.id}"
        )
        assert saved.json() == frame
        selected.refresh_from_db()
        untouched.refresh_from_db()
        self.widget.refresh_from_db()
        self.node_run.refresh_from_db()
        assert selected.canvas_source_version_id == original_source
        assert untouched.demo_data == original_demo
        assert self.widget.current_version_id == self.version.id
        assert self.widget.pending_version_id == draft.id
        assert self.node_run.envelope["first_page"][0] == ["Plan 0", 0]

    @parameterized.expand([("historical", 409), ("other_project", 404), ("invalid_row", 400), ("oversized", 400)])
    def test_demo_edits_reject_invalid_targets_and_rows(self, scenario: str, expected_status: int) -> None:
        self._publish()
        self.version.refresh_from_db()
        original_demo = self.version.demo_data
        target_id = self.version.id
        if scenario == "historical":
            older = GeneratedWidgetVersion.objects.for_team(self.team.id).create(
                team_id=self.team.id, widget=self.widget, canvas_source_version_id=uuid4()
            )
            target_id = older.id
        elif scenario == "other_project":
            other_team = Team.objects.create(organization=self.organization)
            GeneratedWidget.objects.for_team(self.team.id).filter(id=self.widget.id).update(team_id=other_team.id)
        rows: list[list[object]] = [["Starter", 250]]
        if scenario == "invalid_row":
            rows = [["Missing revenue"]]
        elif scenario == "oversized":
            rows = [["x" * (512 * 1_024), 250]]
        response = self.client.post(
            f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/demo-data/",
            data={"version_id": str(target_id), "frame_name": self.input_name, "rows": rows},
            format="json",
        )
        assert response.status_code == expected_status, response.json()
        self.version.refresh_from_db()
        assert self.version.demo_data == original_demo

    @parameterized.expand([("session_read", False, False), ("session_edit", False, True), ("token_read", True, False)])
    def test_demo_rows_require_query_access(self, _name: str, token: bool, edit: bool) -> None:
        self._publish()
        if token:
            token_value = generate_random_token()
            PersonalAPIKey.objects.create(
                user=self.user,
                label="Notebook only",
                scopes=["notebook:read"],
                secure_value=hash_key_value(token_value),
            )
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_value}")
        else:
            self._restrict_resource_access("query")
        url = f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/"
        if edit:
            response = self.client.post(
                url + "demo-data/",
                {"version_id": str(self.version.id), "frame_name": self.input_name, "rows": [["Example", 1]]},
                format="json",
            )
        else:
            response = self.client.get(url + f"frames/{self.input_name}/")
        assert response.status_code == 403

    def _restrict_resource_access(self, resource: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save(update_fields=["level"])
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=None,
            organization_member=self.organization_membership,
            access_level="none",
        )
        cache.clear()

    @parameterized.expand(
        [
            ("read", ""),
            ("generate", "generate/"),
            ("save", "save-version/"),
            ("discard", "discard-version/"),
            ("restore", "restore/"),
            ("demo", "demo-data/"),
        ]
    )
    def test_single_notebook_editor_cannot_control_the_catalog(self, _name: str, action: str) -> None:
        self._publish()
        self._restrict_resource_access("notebook")
        AccessControl.objects.create(
            team=self.team,
            resource="notebook",
            resource_id=str(self.notebook.id),
            organization_member=self.organization_membership,
            access_level="editor",
        )
        cache.clear()
        url = f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/{action}"
        response = self.client.post(url, {}, format="json") if action else self.client.get(url)
        assert response.status_code == 403

    def test_catalog_lists_only_published_widgets_for_the_team(self) -> None:
        assert list_reusable_widgets(team_id=self.team.id).count == 0
        assert reusable_widget_catalog_context(team_id=self.team.id, user=self.user) == ""
        self._publish()

        response = self.client.get(f"/api/projects/{self.team.id}/notebook_widgets/?search=revenue")

        assert response.status_code == 200
        assert response.json()["count"] == 1
        assert response.json()["results"][0]["id"] == str(self.widget.id)
        assert response.json()["results"][0]["instance_count"] == 1
        other_team = Team.objects.create(organization=self.organization)
        assert list_reusable_widgets(team_id=other_team.id).count == 0
        assert reusable_widget_catalog_context(team_id=other_team.id, user=self.user) == ""
        context = reusable_widget_catalog_context(team_id=self.team.id, user=self.user)
        entries = json.loads(context.split("\n", 1)[1])
        assert entries[0]["id"] == str(self.widget.id)
        assert entries[0]["inputs"][0]["slot"] == self.input_name
        assert "demo_data" not in entries[0]
        assert "MDX" in context
        with patch("products.notebooks.backend.reusable_widgets.is_notebook_widget_enabled", return_value=False):
            assert reusable_widget_catalog_context(team_id=self.team.id, user=self.user) == ""

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

    def test_shared_edit_stages_a_review_draft_without_changing_the_published_version(self) -> None:
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

        draft_source_version_id = uuid4()
        with (
            patch(
                "products.notebooks.backend.widget_generation.generate_widget_source",
                return_value=GeneratedWidgetSource(
                    title="Stacked revenue by plan",
                    source="export default function Widget() { return null }",
                ),
            ),
            patch(
                "products.notebooks.backend.widget_generation.review_widget_source",
                return_value=WidgetSecurityReview(
                    severity="none",
                    summary="No security issues found.",
                    findings=[],
                    model=WIDGET_SECURITY_REVIEW_MODEL,
                    review_version="2",
                ),
            ),
            patch("products.canvas.backend.notebook_integration.get_notebook_canvas_source", return_value="source"),
            patch("products.canvas.backend.notebook_integration.prepare_notebook_canvas_source", return_value=object()),
            patch(
                "products.canvas.backend.notebook_integration.publish_prepared_notebook_canvas_draft",
                return_value=draft_source_version_id,
            ) as stage_draft,
            patch("products.canvas.backend.notebook_integration.publish_prepared_notebook_canvas_source") as publish,
        ):
            run_widget_generation_job(job.id, self.team.id)

        self.widget.refresh_from_db()
        job.refresh_from_db()
        assert job.status == GeneratedWidgetGenerationJob.Status.COMPLETED
        assert self.widget.current_version_id == self.version.id
        assert self.widget.pending_version_id == job.result_version_id
        assert self.widget.pending_version is not None
        assert self.widget.pending_version.canvas_source_version_id == draft_source_version_id
        with patch(
            "products.canvas.backend.notebook_integration.list_notebook_canvas_versions",
            return_value=[self._canvas_version()],
        ):
            history = list_widget_versions(notebook=self.notebook, node_id=self.node_id)
        assert [version.id for version in history.results] == [self.version.id]
        with self.assertRaises(WidgetError) as error:
            set_widget_instance_version(
                notebook=self.notebook,
                node_id=self.node_id,
                version_id=self.widget.pending_version_id,
            )
        assert error.exception.code == "version_missing"
        stage_draft.assert_called_once()
        publish.assert_not_called()

    def test_saving_a_reviewed_draft_advances_the_shared_version(self) -> None:
        self._publish()
        candidate = GeneratedWidgetVersion.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            widget=self.widget,
            canvas_source_version_id=uuid4(),
            parent_version=self.version,
            title="Stacked revenue by plan",
            operation=GeneratedWidgetVersion.Operation.IMPROVE,
            prompt_delta="Use a stacked bar chart",
            generator_version="4",
            input_contract=self.version.input_contract,
            demo_data=self.version.demo_data,
            schema_hash="",
            created_by=self.user,
        )
        self.widget.pending_version = candidate
        self.widget.save(update_fields=["pending_version"])
        url = f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/save-version/"

        def canvas_versions(*, version_ids: list[UUID], **_kwargs: object) -> list[NotebookCanvasVersion]:
            return [
                NotebookCanvasVersion(
                    id=version_ids[0],
                    build_status="ready",
                    artifact_url="https://example.com/reviewed-widget.html",
                    build_hash="f" * 64,
                )
            ]

        with (
            patch(
                "products.canvas.backend.notebook_integration.list_notebook_canvas_versions",
                side_effect=canvas_versions,
            ),
            patch("products.canvas.backend.notebook_integration.promote_notebook_canvas_draft") as promote,
        ):
            response = self.client.post(
                url,
                data={
                    "pending_version_id": str(candidate.id),
                    "expected_current_version_id": str(self.version.id),
                },
                format="json",
            )

        assert response.status_code == 200
        assert response.json()["current_version"]["id"] == str(candidate.id)
        assert response.json()["pending_version"] is None
        assert response.json()["version_count"] == 2
        self.widget.refresh_from_db()
        assert self.widget.current_version_id == candidate.id
        assert self.widget.pending_version_id is None
        promote.assert_called_once_with(
            team_id=self.team.id,
            canvas_id=self.widget.canvas_id,
            user_id=self.user.id,
            version_id=candidate.canvas_source_version_id,
            expected_current_version_id=self.version.canvas_source_version_id,
        )

    @patch("products.canvas.backend.notebook_integration.discard_notebook_canvas_draft")
    def test_discarding_a_review_draft_keeps_the_published_version(self, discard) -> None:
        self._publish()
        candidate = GeneratedWidgetVersion.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            widget=self.widget,
            canvas_source_version_id=uuid4(),
            parent_version=self.version,
            title="Unwanted draft",
            operation=GeneratedWidgetVersion.Operation.IMPROVE,
            prompt_delta="Change everything",
            generator_version="4",
            input_contract=self.version.input_contract,
            schema_hash="",
            created_by=self.user,
        )
        self.widget.pending_version = candidate
        self.widget.save(update_fields=["pending_version"])
        url = f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/discard-version/"
        with patch(
            "products.canvas.backend.notebook_integration.list_notebook_canvas_versions",
            return_value=[self._canvas_version()],
        ):
            response = self.client.post(
                url,
                data={
                    "pending_version_id": str(candidate.id),
                    "expected_current_version_id": str(self.version.id),
                },
                format="json",
            )

        assert response.status_code == 200
        assert response.json()["current_version"]["id"] == str(self.version.id)
        assert response.json()["pending_version"] is None
        discard.assert_called_once_with(
            team_id=self.team.id, canvas_id=self.widget.canvas_id, version_id=candidate.canvas_source_version_id
        )
        self.widget.refresh_from_db()
        assert self.widget.current_version_id == self.version.id
        assert self.widget.pending_version_id is None
        assert not GeneratedWidgetVersion.objects.for_team(self.team.id).filter(id=candidate.id).exists()

    def _add_published_version(self) -> GeneratedWidgetVersion:
        version = GeneratedWidgetVersion.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            widget=self.widget,
            canvas_source_version_id=uuid4(),
            parent_version=self.version,
            title="Revenue over time",
            operation=GeneratedWidgetVersion.Operation.IMPROVE,
            input_contract=[],
            demo_data={},
            created_by=self.user,
        )
        self.widget.current_version = version
        self.widget.save(update_fields=["current_version"])
        return version

    def test_catalog_history_pages_keep_versions_and_their_preview_data_together(self) -> None:
        self._publish()
        latest = self._add_published_version()
        draft = GeneratedWidgetVersion.objects.for_team(self.team.id).create(
            team_id=self.team.id, widget=self.widget, canvas_source_version_id=uuid4()
        )
        self.widget.pending_version = draft
        self.widget.save(update_fields=["pending_version"])
        url = f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/versions/"
        canvas_versions = [
            self._canvas_version(),
            NotebookCanvasVersion(
                id=latest.canvas_source_version_id, build_status="ready", artifact_url="https://example.com/latest.html"
            ),
        ]
        with patch(
            "products.canvas.backend.notebook_integration.list_notebook_canvas_versions", return_value=canvas_versions
        ):
            response = self.client.get(url, {"limit": 1})
            older = self.client.get(url, {"offset": 1, "limit": 1})
        assert response.status_code == 200
        assert response.json()["count"] == 2
        assert response.json()["next_offset"] == 1
        assert response.json()["results"][0]["id"] == str(latest.id)
        assert response.json()["results"][0]["version"] == 2
        assert response.json()["results"][0]["input_contract"] == []
        assert older.json()["next_offset"] is None
        assert older.json()["results"][0]["id"] == str(self.version.id)
        assert older.json()["results"][0]["version"] == 1
        assert older.json()["results"][0]["input_contract"][0]["slot"] == self.input_name
        assert older.json()["results"][0]["artifact_url"] == self._canvas_version().artifact_url
        assert self.client.get(url, {"limit": 0}).status_code == 400
        assert self.client.get(f"/api/projects/{self.team.id}/notebook_widgets/{uuid4()}/versions/").status_code == 404

    def test_making_an_older_version_latest_preserves_history_pins_and_demo_data(self) -> None:
        self._publish()
        self.version.refresh_from_db()
        latest = self._add_published_version()
        self.instance.pinned_version = latest
        self.instance.save(update_fields=["pinned_version"])
        self.version.security_review_severity = "none"
        self.version.security_reviewed_at = timezone.now()
        self.version.model = "claude-sonnet-4.6"
        self.version.save(update_fields=["security_review_severity", "security_reviewed_at", "model"])
        source_version_id = uuid4()
        with (
            patch(
                "products.canvas.backend.notebook_integration.get_notebook_canvas_source",
                return_value="export default function Widget() { return null }",
            ),
            patch("products.canvas.backend.notebook_integration.prepare_notebook_canvas_source", return_value=object()),
            patch(
                "products.canvas.backend.notebook_integration.publish_prepared_notebook_canvas_source",
                return_value=source_version_id,
            ),
            patch(
                "products.canvas.backend.notebook_integration.list_notebook_canvas_versions",
                return_value=[self._canvas_version()],
            ),
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/restore/",
                {"version_id": str(self.version.id), "expected_current_version_id": str(latest.id)},
                format="json",
            )
        assert response.status_code == 200
        assert response.json()["current_version"]["version"] == 3
        self.widget.refresh_from_db()
        self.instance.refresh_from_db()
        restored = self.widget.current_version
        assert restored is not None
        assert restored.id not in {self.version.id, latest.id}
        assert restored.reverted_from_version_id == self.version.id
        assert restored.parent_version_id == latest.id
        assert restored.input_contract == self.version.input_contract
        assert restored.demo_data == self.version.demo_data
        assert restored.security_review_severity == "none"
        assert restored.model == self.version.model
        assert restored.canvas_source_version_id == source_version_id
        assert self.instance.pinned_version_id == latest.id
        assert GeneratedWidgetVersion.objects.for_team(self.team.id).filter(widget=self.widget).count() == 3

    @parameterized.expand(["stale", "pending", "active", "foreign_widget", "foreign_team"])
    def test_restore_rejects_conflicts_and_versions_outside_the_widget(self, reason: str) -> None:
        self._publish()
        latest = self._add_published_version()
        expected = latest.id
        target = self.version.id
        if reason == "stale":
            expected = self.version.id
        elif reason == "pending":
            self.widget.pending_version = self.version
            self.widget.save(update_fields=["pending_version"])
        elif reason == "active":
            GeneratedWidgetGenerationJob.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                widget=self.widget,
                instance=self.instance,
                status=GeneratedWidgetGenerationJob.Status.GENERATING,
                base_version=latest,
            )
        else:
            team = self.team if reason == "foreign_widget" else Team.objects.create(organization=self.organization)
            foreign_widget = GeneratedWidget.objects.for_team(team.id).create(team_id=team.id, canvas_id=uuid4())
            target = (
                GeneratedWidgetVersion.objects.for_team(team.id)
                .create(team_id=team.id, widget=foreign_widget, canvas_source_version_id=uuid4())
                .id
            )
        response = self.client.post(
            f"/api/projects/{self.team.id}/notebook_widgets/{self.widget.id}/restore/",
            {"version_id": str(target), "expected_current_version_id": str(expected)},
            format="json",
        )
        assert response.status_code == (400 if reason.startswith("foreign") else 409)
        self.widget.refresh_from_db()
        assert self.widget.current_version_id == latest.id
        assert GeneratedWidgetVersion.objects.for_team(self.team.id).filter(widget=self.widget).count() == 2

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
        assert self.instance.pinned_version_id is None
        assert response.json()["current_version_id"] == str(self.instance.widget.current_version_id)
        assert self.instance.widget.current_version is not None
        assert self.instance.widget.current_version.canvas_source_version_id == forked_source_version_id
