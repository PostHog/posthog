from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.hogql.direct_sql.mysql_adapter import MySQLAdapter

from posthog.clickhouse.query_tagging import Product, get_query_tags

from products.notebooks.backend.kernel_runtime import build_notebook_sandbox_config
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook, NotebookAppRelease, NotebookNodeRun

CAPACITY = '<PythonV2 nodeId="capacity" code="print(orders * minutes // 60)" />'


@patch("products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled", return_value=True)
class TestAppCompute(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.defaults = [
            {"name": "orders", "type": "number", "value": 120},
            {"name": "minutes", "type": "number", "value": 10},
        ]
        self.layout = {"blocks": [{"kind": "input", "variable": "orders"}, {"kind": "cell", "node_id": "capacity"}]}
        self.notebook = Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            variables=self.defaults,
            content=build_markdown_notebook_content("Edited notebook"),
            app_published=self.layout,
            app_revision=1,
        )
        self.release = NotebookAppRelease.objects.for_team(self.team.id).create(
            team=self.team,
            notebook=self.notebook,
            revision=1,
            layout=self.layout,
            markdown=CAPACITY,
            variables=self.defaults,
            title="Capacity",
        )
        self.url = f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/app_compute/"
        self.payload = {
            "node_id": "capacity",
            "revision": 1,
            "variables": [{"name": "orders", "type": "number", "value": 240}],
        }

    def test_editor_runs_only_the_current_saved_sources_in_an_unpublished_preview(self, _flag) -> None:
        self.release.delete()
        self.notebook.app_published = None
        self.notebook.content = build_markdown_notebook_content(CAPACITY)
        self.notebook.save(update_fields=["app_published", "content"])
        layout = {
            "tabs": [{"id": "main", "title": "Main"}],
            "blocks": [
                {"id": "orders", "kind": "input", "variable": "orders", "tab_id": "main"},
                {"id": "output", "kind": "cell", "node_id": "capacity", "tab_id": "main"},
            ],
        }
        url = self.url.replace("app_compute", "app_draft_compute")
        payload = {**self.payload, "revision": self.notebook.version, "layout": layout}
        kernel = MagicMock()
        kernel.execute.return_value = SimpleNamespace(status="ok", stdout="40", result=None)
        with patch("products.notebooks.backend.app_compute.get_kernel_runtime", return_value=kernel):
            assert (
                self.client.post(url, {**payload, "revision": self.notebook.version + 1}, format="json").status_code
                == 409
            )
            response = self.client.post(url, payload, format="json")
            assert response.status_code == 200, response.json()
            assert response.json() == {"text": "40"}
            kernel.shutdown.assert_called_once()
        self.notebook.refresh_from_db()
        assert self.notebook.variables == self.defaults and self.notebook.app_published is None

    def test_viewer_inputs_and_kernel_are_private_to_one_run(self, _flag) -> None:
        kernel = MagicMock()
        kernel.execute.return_value = SimpleNamespace(status="ok", stdout="40\n", result=None)
        with patch("products.notebooks.backend.app_compute.get_kernel_runtime", return_value=kernel) as get_kernel:
            other = self._create_user("viewer@example.com")
            self.organization.members.add(other)
            for actor in (self.user, other):
                self.client.force_login(actor)
                response = self.client.post(self.url, self.payload, format="json")
                assert response.status_code == 200, response.json()
                assert response.json() == {"text": "40\n"}
            scratches = [call.args[0] for call in get_kernel.call_args_list]
            assert [call.args[1] for call in get_kernel.call_args_list] == [self.user, other]
            assert scratches[0].short_id != scratches[1].short_id
            assert all(
                scratch._state.adding and build_notebook_sandbox_config(scratch).block_network for scratch in scratches
            )
            assert kernel.shutdown.call_count == 2
            assert kernel.execute.call_args.args[0] == "print(orders * minutes // 60)"
        self.notebook.refresh_from_db()
        assert self.notebook.variables == self.defaults
        assert not NotebookNodeRun.objects.for_team(self.team.id).filter(notebook=self.notebook).exists()

    def test_rejects_missing_scope_hidden_cells_and_outdated_sources(self, _flag) -> None:
        with patch(
            "products.notebooks.backend.presentation.views.notebook.NotebookViewSet._has_query_access",
            return_value=False,
        ):
            assert self.client.post(self.url, self.payload, format="json").status_code == 403
        cases: list[tuple[dict[str, object], int]] = [
            ({"revision": 2}, 409),
            ({"node_id": "private"}, 400),
            ({"variables": [{"name": "minutes", "type": "number", "value": 20}]}, 400),
        ]
        for updates, status in cases:
            assert self.client.post(self.url, {**self.payload, **updates}, format="json").status_code == status
        self.release.delete()
        response = self.client.post(self.url, self.payload, format="json")
        assert response.status_code == 409 and "publish" in response.json()["detail"]

    def test_connected_hogql_preserves_viewer_identity_and_connection(self, _flag) -> None:
        connection_id = str(uuid4())
        self.release.markdown = (
            f'<SQLV2 nodeId="capacity" code="SELECT {{orders}} AS jobs" connectionId="{connection_id}" />'
        )
        self.release.save(update_fields=["markdown"])

        def run_query(**kwargs):
            assert kwargs["user"] == self.user
            assert kwargs["connection_id"] == connection_id
            assert "240" in kwargs["query"]
            assert get_query_tags().product == Product.NOTEBOOKS
            return SimpleNamespace(error=None, columns=["jobs"], results=[[240]])

        with patch("products.notebooks.backend.app_compute.execute_hogql_query", side_effect=run_query):
            response = self.client.post(self.url, self.payload, format="json")
            assert response.status_code == 200, response.json()
            assert response.json() == {"columns": ["jobs"], "rows": [[240]]}

    def test_oversized_or_nonfinite_upstream_frame_never_reaches_the_python_cell(self, _flag) -> None:
        self.release.markdown = (
            '<SQLV2 nodeId="source" code="SELECT 1 AS value" returnVariable="jobs" />\n\n'
            '<PythonV2 nodeId="capacity" code="print(len(jobs))" />'
        )
        self.release.save(update_fields=["markdown"])
        kernel = MagicMock()
        kernel.execute.return_value = SimpleNamespace(status="ok", stdout="", result=None)
        with (
            patch("products.notebooks.backend.app_compute.get_kernel_runtime", return_value=kernel),
            patch("products.notebooks.backend.app_compute.execute_hogql_query") as query,
        ):
            for rows, reason in [
                ([[1]] * 501, "500 rows"),
                ([["long value"]], "too large"),
                ([[float("nan")]], "non-finite"),
            ]:
                query.return_value = SimpleNamespace(error=None, columns=["jobs"], results=rows)
                with patch("products.notebooks.backend.app_compute.APP_VIEWER_MAX_OUTPUT_BYTES", 32):
                    response = self.client.post(self.url, self.payload, format="json")
                assert response.status_code == 400, response.content
                assert reason in response.json()["detail"]
            assert all("print(len(jobs))" not in call.args[0] for call in kernel.execute.call_args_list)
            assert kernel.shutdown.call_count == 3
        assert not NotebookNodeRun.objects.for_team(self.team.id).filter(notebook=self.notebook).exists()

    def test_native_queries_use_the_read_only_adapter_and_reject_organization_grants(self, _flag) -> None:
        connection_id = str(uuid4())

        def publish(code):
            self.release.markdown = (
                f'<SQLV2 nodeId="capacity" code="{code}" sendRawQuery={{true}} connectionId="{connection_id}" />'
            )
            self.release.save(update_fields=["markdown"])

        with (
            patch(
                "products.notebooks.backend.app_compute.get_direct_connection_source", return_value=object()
            ) as source,
            patch(
                "products.notebooks.backend.app_compute.raw_query_uses_organization_grant", return_value=False
            ) as org_grant,
            patch(
                "products.notebooks.backend.app_compute.get_raw_adapter_for_source",
                return_value=MySQLAdapter(),
            ),
            patch(
                "products.notebooks.backend.app_compute.execute_hogql_query",
                return_value=SimpleNamespace(error=None, columns=["capacity"], results=[[8]]),
            ) as query,
        ):
            publish("SELECT 8 AS capacity")
            response = self.client.post(self.url, self.payload, format="json")
            assert response.status_code == 200, response.json()
            assert query.call_args.kwargs["send_raw_query"]
            assert source.call_args.kwargs["user"] == self.user
            publish("SELECT {orders} AS capacity")
            assert self.client.post(self.url, self.payload, format="json").status_code == 400
            publish("SELECT 8 AS capacity")
            org_grant.return_value = True
            assert self.client.post(self.url, self.payload, format="json").status_code == 400
            assert query.call_count == 1
