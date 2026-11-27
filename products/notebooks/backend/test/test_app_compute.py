import json
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import connection

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult
from posthog.hogql.direct_sql.mysql_adapter import MySQLAdapter
from posthog.hogql.direct_sql.result_limit import execute_with_result_limit
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.timings import HogQLTimings

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import Product, get_query_tags

from products.notebooks.backend.kernel_runtime import KernelRuntimeService, build_notebook_sandbox_config
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
        kernel.execute.side_effect = lambda code, **kwargs: SimpleNamespace(
            status="ok", stdout="null" if "print(json.dumps(notebook_dataframe_page" in code else "40", result=None
        )
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
        kernel.execute.side_effect = lambda code, **kwargs: SimpleNamespace(
            status="ok", stdout="null" if "print(json.dumps(notebook_dataframe_page" in code else "40\n", result=None
        )
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
            assert any("print(orders * minutes // 60)" in call.args[0] for call in kernel.execute.call_args_list)
        self.notebook.refresh_from_db()
        assert self.notebook.variables == self.defaults
        assert not NotebookNodeRun.objects.for_team(self.team.id).filter(notebook=self.notebook).exists()

    def test_sql_only_chain_inlines_hogql_without_a_sandbox(self, _flag) -> None:
        self.release.markdown = (
            '<SQLV2 nodeId="events" code="SELECT person_id FROM events" returnVariable="people" />\n\n'
            '<SQLV2 nodeId="capacity" code="SELECT uniqExact(person_id) FROM people" />'
        )
        self.release.save(update_fields=["markdown"])
        with (
            patch("products.notebooks.backend.app_compute.get_kernel_runtime") as sandbox,
            patch("products.notebooks.backend.app_compute.execute_hogql_query") as query,
        ):
            query.return_value = SimpleNamespace(error=None, columns=["people"], results=[[4]])
            response = self.client.post(self.url, self.payload, format="json")
        assert response.status_code == 200, response.content
        assert response.json()["rows"] == [[4]]
        query.assert_called_once()
        assert "uniqExact" in query.call_args.kwargs["query"] and "events" in query.call_args.kwargs["query"]
        sandbox.assert_not_called()

    def test_full_organization_query_budget_refuses_private_sql(self, _flag) -> None:
        self.release.markdown = '<SQLV2 nodeId="capacity" code="SELECT 1" />'
        self.release.save(update_fields=["markdown"])
        with (
            patch(
                "products.notebooks.backend.app_compute.app_org_concurrency_slot",
                side_effect=ConcurrencyLimitExceeded("busy"),
            ),
            patch("products.notebooks.backend.app_compute.execute_hogql_query") as query,
        ):
            response = self.client.post(self.url, self.payload, format="json")
        assert response.status_code == 429 and response["Retry-After"]
        query.assert_not_called()

    def test_native_query_byte_budget_fails_cleanly_before_display(self, _flag) -> None:
        self.release.markdown = '<SQLV2 nodeId="capacity" code="SELECT repeat(\'a\', 3000) AS reading" />'
        self.release.save(update_fields=["markdown"])
        ordinary = self.client.post(self.url, self.payload, format="json")
        assert ordinary.status_code == 200, ordinary.content
        assert ordinary.json()["rows"] == [["a" * 3000]]
        with patch("products.notebooks.backend.app_compute.APP_VIEWER_MAX_OUTPUT_BYTES", 1024):
            response = self.client.post(self.url, self.payload, format="json")
        assert response.status_code == 400, response.content
        assert "detail" in response.json()

    def test_database_byte_budget_preserves_columns_and_stops_values_at_the_connection(self, _flag) -> None:
        adapter = MagicMock(engine="postgres")
        received = []

        def execute(request):
            with connection.cursor() as cursor:
                cursor.execute(request.sql, request.values)
                rows = cursor.fetchall()
                received.append(rows)
                names = [col.name for col in cursor.description]
            return DirectQueryResult(results=rows, types=[(name, "String") for name in names], print_columns=names)

        adapter.execute.side_effect = execute
        request = DirectQueryRequest(
            source=MagicMock(),
            team=self.team,
            sql='SELECT repeat(%(letter)s, 10) AS "daily total" FROM generate_series(1, 3)',
            values={"letter": "a"},
            settings=HogQLGlobalSettings(max_result_bytes=120),
            timings=HogQLTimings(),
            query_type="test",
            debug=False,
        )
        result = execute_with_result_limit(adapter, request)
        assert result.print_columns == ["daily total"] and result.results == [("a" * 10,)] * 3
        request.settings.max_result_bytes = 42
        with pytest.raises(ExposedHogQLError, match="too large"):
            execute_with_result_limit(adapter, request)
        assert received[-2] == []
        assert len(received[-1]) == 3 and all(value is None and size > 42 for value, size in received[-1])

        request.sql = 'SELECT 1 AS source_row, 2 AS source_row_1, 3 AS "_POSTHOG_RESULT_BYTES"'
        request.values = None
        request.settings.max_result_bytes = 120
        named_columns = execute_with_result_limit(adapter, request)
        assert named_columns.print_columns == ["source_row", "source_row_1", "_POSTHOG_RESULT_BYTES"]
        assert named_columns.results == [(1, 2, 3)]

        request.sql = "SELECT 42 AS total WHERE false"
        assert execute_with_result_limit(adapter, request).results == []

    def test_private_frames_use_notebook_expression_semantics_and_bound_intermediate_sql(self, _flag) -> None:
        from IPython.core.interactiveshell import InteractiveShell

        shell = InteractiveShell()
        shell.run_cell(KernelRuntimeService()._build_kernel_bootstrap_code(self.notebook, self.user, "test"))

        def run(code, **kwargs):
            stdout = StringIO()
            with redirect_stdout(stdout):
                outcome = shell.run_cell(code, store_history=True)
            return SimpleNamespace(
                status="ok" if outcome.success else "error",
                stdout=stdout.getvalue(),
                result=None,
                stderr=str(outcome.error_in_exec or outcome.error_before_exec or ""),
                error_name="",
            )

        kernel = MagicMock()
        kernel.execute.side_effect = run

        def node(kind, node_id, name, code):
            return f'<{kind} nodeId="{node_id}" returnVariable="{name}" code={{{json.dumps(code)}}} />'

        with patch("products.notebooks.backend.app_compute.get_kernel_runtime", return_value=kernel):
            for code in ("forecasts = pd.DataFrame({'total': [4]})", "pd.Series([4], name='total')"):
                self.release.markdown = node("PythonV2", "capacity", "forecasts", code)
                self.release.save(update_fields=["markdown"])
                response = self.client.post(self.url, self.payload, format="json")
                assert response.status_code == 200, response.content
                assert response.json() == {"columns": ["total"], "rows": [[4]]}
            self.release.markdown = "\n\n".join(
                (
                    node("PythonV2", "source", "forecasts", "pd.DataFrame({'total': [4]})"),
                    node("SQLV2", "many", "expanded", "SELECT total FROM forecasts CROSS JOIN range(700)"),
                    node("PythonV2", "capacity", "reduced", "print(len(expanded))"),
                )
            )
            self.release.save(update_fields=["markdown"])
            response = self.client.post(self.url, self.payload, format="json")
            assert response.status_code == 400, response.content
            assert "500 rows" in response.json()["detail"]
            assert not any("print(len(expanded))" in call.args[0] for call in kernel.execute.call_args_list)

    def test_kernel_timeout_is_a_calculation_error_and_shuts_down_the_sandbox(self, _flag) -> None:
        kernel = MagicMock()
        kernel.execute.side_effect = TimeoutError("time limit")
        with patch("products.notebooks.backend.app_compute.get_kernel_runtime", return_value=kernel):
            response = self.client.post(self.url, self.payload, format="json")
        assert response.status_code == 400 and "timed out" in response.json()["detail"]
        kernel.shutdown.assert_called_once()

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
            assert 0 < kwargs["settings"].max_execution_time <= 90
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
