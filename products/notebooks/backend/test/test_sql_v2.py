import io
import json
import math
import tarfile
import datetime
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core import signing
from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope

from products.notebooks.backend.kernel_package import kernel_package_bytes_and_hash
from products.notebooks.backend.models import KernelRuntime, Notebook, NotebookNodeRun
from products.notebooks.backend.sandbox.kernel import (
    auth as kernel_auth,
    envelope as kernel_envelope,
    runner as kernel_runner,
)
from products.notebooks.backend.sandbox.kernel.data_plane import (
    DataPlaneError,
    DataPlaneInterrupted,
    decode_arrow_stream,
)
from products.notebooks.backend.sql_v2 import (
    SQLV2KernelNotRunning,
    SQLV2PageError,
    dispatch_sql_v2_run,
    ensure_sql_v2_server,
    fetch_sql_v2_page,
    kernel_server_secret,
    mint_callback_token,
    mint_command_token,
    mint_data_plane_token,
    sql_v2_page_lock_key,
    verify_data_plane_token,
)
from products.notebooks.backend.sql_v2_callback import MAX_ENVELOPE_BYTES
from products.notebooks.backend.sql_v2_data_plane import _rows_to_arrow_bytes
from products.notebooks.backend.temporal.sql_v2 import (
    SQLV2RunInput,
    dispatch_sql_v2_run_activity,
    mark_sql_v2_run_failed_activity,
)

from ee.models.rbac.access_control import AccessControl


def _restrict_query_access(test: APIBaseTest) -> None:
    # Demote from owner (owner bypasses access control) to member, turn on the ACCESS_CONTROL
    # feature, and write an explicit query "none" row so the user falls below query-read.
    test.organization.available_product_features = [
        {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
    ]
    test.organization.save(update_fields=["available_product_features"])
    test.organization_membership.level = OrganizationMembership.Level.MEMBER
    test.organization_membership.save(update_fields=["level"])
    AccessControl.objects.create(
        team=test.team,
        resource="query",
        resource_id=None,
        organization_member=test.organization_membership,
        access_level="none",
    )
    cache.clear()


class TestSQLV2Callback(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, short_id="nbcb123")
        with team_scope(self.team.id):
            self.node_run = NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                node_id="node-1",
                status=NotebookNodeRun.Status.RUNNING,
            )
        self.url = f"/internal/notebooks/runs/{self.node_run.id}/result/"
        self.envelope = {
            "status": "ok",
            "columns": ["count"],
            "row_count": 1,
            "first_page": [[42]],
            "result_id": str(self.node_run.id),
        }

    def _post(self, token: str, envelope=None):
        return self.client.post(
            self.url,
            data=json.dumps({"envelope": envelope if envelope is not None else self.envelope}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def _reload_run(self) -> NotebookNodeRun:
        return NotebookNodeRun.objects.for_team(self.team.id).get(id=self.node_run.id)

    def test_valid_token_stores_result(self):
        token = mint_callback_token(str(self.node_run.id), self.team.id)
        response = self._post(token)
        self.assertEqual(response.status_code, 200)
        run = self._reload_run()
        self.assertEqual(run.status, NotebookNodeRun.Status.DONE)
        self.assertEqual(run.envelope["first_page"], [[42]])
        self.assertEqual(str(run.result_id), str(self.node_run.id))

    def test_interrupted_envelope_marks_run_interrupted(self):
        # A user-requested stop must not surface as a red FAILED run, and the captured
        # output must be stored for the UI to show.
        token = mint_callback_token(str(self.node_run.id), self.team.id)
        response = self._post(
            token, envelope={"status": "interrupted", "stdout": "partial output", "error": "Run interrupted."}
        )
        self.assertEqual(response.status_code, 200)
        run = self._reload_run()
        self.assertEqual(run.status, NotebookNodeRun.Status.INTERRUPTED)
        self.assertEqual(run.envelope["stdout"], "partial output")
        self.assertEqual(run.error, "Run interrupted.")

    def test_redelivery_is_idempotent(self):
        token = mint_callback_token(str(self.node_run.id), self.team.id)
        self._post(token)
        self._post(token)
        count = NotebookNodeRun.objects.for_team(self.team.id).filter(id=self.node_run.id).count()
        self.assertEqual(count, 1)
        self.assertEqual(self._reload_run().status, NotebookNodeRun.Status.DONE)

    @parameterized.expand(
        [
            ("missing_token", None, 401),
            ("garbage_token", "not-a-real-token", 401),
        ]
    )
    def test_rejects_bad_auth(self, _name, token, expected_status):
        if token is None:
            response = self.client.post(
                self.url, data=json.dumps({"envelope": self.envelope}), content_type="application/json"
            )
        else:
            response = self._post(token)
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(self._reload_run().status, NotebookNodeRun.Status.RUNNING)

    def test_token_for_other_run_is_forbidden(self):
        token = mint_callback_token("00000000-0000-0000-0000-0000000000ff", self.team.id)
        response = self._post(token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._reload_run().status, NotebookNodeRun.Status.RUNNING)

    def test_oversized_envelope_is_rejected(self):
        token = mint_callback_token(str(self.node_run.id), self.team.id)
        response = self._post(token, envelope={**self.envelope, "stdout": "x" * (MAX_ENVELOPE_BYTES + 1)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._reload_run().status, NotebookNodeRun.Status.RUNNING)

    def test_unknown_run_returns_404(self):
        other_id = "00000000-0000-0000-0000-000000000000"
        token = mint_callback_token(other_id, self.team.id)
        response = self.client.post(
            f"/internal/notebooks/runs/{other_id}/result/",
            data=json.dumps({"envelope": self.envelope}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 404)


class TestSQLV2Run(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, short_id="nbrun01")
        self.run_url = f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/sql_v2/run/"

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_run_creates_row_and_starts_workflow(self, _mock_enabled, mock_start):
        response = self.client.post(self.run_url, data={"node_id": "n1", "code": "select 1"}, format="json")
        self.assertEqual(response.status_code, 200)
        run_id = response.json()["run_id"]
        run = NotebookNodeRun.objects.for_team(self.team.id).get(id=run_id)
        self.assertEqual(run.status, NotebookNodeRun.Status.RUNNING)
        # Paging re-queries the run's stored code, so losing it here breaks every page fetch.
        self.assertEqual(run.code, "select 1")
        mock_start.assert_called_once()
        self.assertEqual(str(mock_start.call_args.args[0].run_id), run_id)

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_query_restricted_member_cannot_run(self, _mock_enabled, mock_start):
        # A notebook editor whose query access is denied must not execute HogQL through the node.
        _restrict_query_access(self)
        response = self.client.post(self.run_url, data={"node_id": "n1", "code": "select 1"}, format="json")
        self.assertEqual(response.status_code, 403)
        mock_start.assert_not_called()
        self.assertFalse(NotebookNodeRun.objects.for_team(self.team.id).exists())

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_blank_code_is_rejected_before_dispatch(self, _mock_enabled, mock_start):
        # A stale-attribute FE bug once sent empty code all the way into the sandbox; fail fast here instead.
        response = self.client.post(self.run_url, data={"node_id": "n1", "code": ""}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(NotebookNodeRun.objects.for_team(self.team.id).filter(notebook=self.notebook).count(), 0)
        mock_start.assert_not_called()

    def _record_done_run(self, node_id: str, code: str) -> None:
        with team_scope(self.team.id):
            NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                node_id=node_id,
                code=code,
                status=NotebookNodeRun.Status.DONE,
            )

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_run_inlines_referenced_nodes_last_run_query_as_ctes(self, _mock_enabled, mock_start):
        # Paging re-queries run.code, so the stored + dispatched query must already carry the
        # referenced definitions as CTEs — and it must be each node's last run, not its live text.
        self._record_done_run("node-df1", "select id from events")
        self._record_done_run("node-df2", "select id from persons")
        response = self.client.post(
            self.run_url,
            data={
                "node_id": "join-node",
                "code": "select * from df1 join df2 on df1.id = df2.id",
                "refs": {"df1": {"node_id": "node-df1"}, "df2": {"node_id": "node-df2"}},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        run = NotebookNodeRun.objects.for_team(self.team.id).get(id=response.json()["run_id"])
        self.assertIn("WITH df1 AS (SELECT id FROM events)", run.code)
        self.assertIn("df2 AS (SELECT id FROM persons)", run.code)
        self.assertEqual(mock_start.call_args.args[0].code, run.code)

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_run_uses_the_latest_done_run_of_a_referenced_node(self, _mock_enabled, mock_start):
        # An edited-then-rerun upstream: only its most recent run should be inlined.
        with freeze_time("2026-07-04T00:00:00Z"):
            self._record_done_run("node-df1", "select 1 as old_col")
        with freeze_time("2026-07-04T00:01:00Z"):
            self._record_done_run("node-df1", "select 2 as new_col")
        response = self.client.post(
            self.run_url,
            data={"node_id": "c", "code": "select * from df1", "refs": {"df1": {"node_id": "node-df1"}}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        run = NotebookNodeRun.objects.for_team(self.team.id).get(id=response.json()["run_id"])
        self.assertIn("new_col", run.code)
        self.assertNotIn("old_col", run.code)

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_hogql_ref_whose_latest_run_was_duckdb_is_treated_as_not_run(self, _mock_enabled, mock_start):
        # A SQL node's runs can alternate engines; a duckdb run's code is raw SQL naming
        # kernel frames, so inlining it as a CTE would ship it to ClickHouse. The stale older
        # hogql run must not be used either — the node's latest result is a local frame.
        with freeze_time("2026-07-04T00:00:00Z"):
            self._record_done_run("node-c", "select id from events")
        with freeze_time("2026-07-04T00:01:00Z"):
            with team_scope(self.team.id):
                NotebookNodeRun.objects.create(
                    team=self.team,
                    notebook=self.notebook,
                    node_id="node-c",
                    code="select * from df2 join new_events on true",
                    node_type=NotebookNodeRun.NodeType.DUCKDB,
                    status=NotebookNodeRun.Status.DONE,
                )
        response = self.client.post(
            self.run_url,
            data={"node_id": "d", "code": "select * from sql_df", "refs": {"sql_df": {"node_id": "node-c"}}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("has not been run", response.json()["detail"])
        mock_start.assert_not_called()

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_hogql_typo_with_refs_present_is_a_400_not_a_500(self, _mock_enabled, mock_start):
        # With refs present the user's code is parsed at dispatch, so a plain typo raises
        # ExposedHogQLError there — it must surface as a bad request, not a server error.
        self._record_done_run("node-df1", "select id from events")
        response = self.client.post(
            self.run_url,
            data={"node_id": "c", "code": "selec 1", "refs": {"df1": {"node_id": "node-df1"}}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        mock_start.assert_not_called()

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_run_rejects_referencing_a_never_run_node(self, _mock_enabled, mock_start):
        response = self.client.post(
            self.run_url,
            data={"node_id": "c", "code": "select * from df1", "refs": {"df1": {"node_id": "node-df1"}}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(NotebookNodeRun.objects.for_team(self.team.id).filter(node_id="c").count(), 0)
        mock_start.assert_not_called()

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_python_node_dispatches_with_materialization_inputs(self, _mock_enabled, mock_start):
        # A python node keeps its code verbatim and ships the frames it reads as materialization inputs.
        self._record_done_run("node-df1", "select id from events")
        response = self.client.post(
            self.run_url,
            data={
                "node_id": "py",
                "node_type": "python",
                "code": "df1.head()",
                "output_name": "result",
                "refs": {"df1": {"node_id": "node-df1"}},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        run = NotebookNodeRun.objects.for_team(self.team.id).get(id=response.json()["run_id"])
        self.assertEqual(run.code, "df1.head()")  # python code stored as-is, not CTE-resolved
        dispatched = mock_start.call_args.args[0]
        self.assertEqual(dispatched.node_type, "python")
        self.assertEqual(dispatched.output_name, "result")
        self.assertEqual([i["name"] for i in dispatched.inputs], ["df1"])
        self.assertEqual(dispatched.inputs[0]["query"], "select id from events")

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_python_node_referencing_a_never_run_node_is_rejected(self, _mock_enabled, mock_start):
        response = self.client.post(
            self.run_url,
            data={
                "node_id": "py",
                "node_type": "python",
                "code": "df1.head()",
                "refs": {"df1": {"node_id": "node-df1"}},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        mock_start.assert_not_called()

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_sql_node_referencing_a_local_frame_reroutes_to_duckdb(self, _mock_enabled, mock_start):
        # Journey 5: a local (Python-made) frame can't push to ClickHouse, so the join runs in
        # the sandbox's DuckDB — SQL as written, hogql refs shipped as materialization inputs.
        self._record_done_run("node-df2", "select id from persons")
        code = "select * from df2 join new_events on df2.id = new_events.id"
        response = self.client.post(
            self.run_url,
            data={
                "node_id": "join-node",
                "code": code,
                "refs": {
                    "df2": {"node_id": "node-df2"},
                    "new_events": {"node_id": "node-py", "kind": "local"},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        run = NotebookNodeRun.objects.for_team(self.team.id).get(id=response.json()["run_id"])
        self.assertEqual(run.node_type, NotebookNodeRun.NodeType.DUCKDB)
        self.assertEqual(run.code, code)  # not CTE-rewritten: DuckDB runs the SQL as written
        dispatched = mock_start.call_args.args[0]
        self.assertEqual(dispatched.node_type, "duckdb")
        self.assertEqual(
            [(i["name"], i["kind"]) for i in dispatched.inputs], [("df2", "hogql"), ("new_events", "local")]
        )

    @patch(
        "products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow",
        side_effect=RuntimeError("temporal unavailable"),
    )
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_run_marks_failed_when_workflow_start_fails(self, _mock_enabled, _mock_start):
        response = self.client.post(self.run_url, data={"node_id": "n1", "code": "select 1"}, format="json")
        self.assertEqual(response.status_code, 503)
        run = NotebookNodeRun.objects.for_team(self.team.id).filter(notebook=self.notebook).first()
        assert run is not None
        self.assertEqual(run.status, NotebookNodeRun.Status.FAILED)


class _RecordingSandbox:
    """Stands in for the docker/Modal sandbox: records control-plane calls."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.commands: list[str] = []

    def write_file(self, path: str, payload: bytes) -> None:
        self.files[path] = payload

    def execute(self, command: str, timeout_seconds: int | None = None) -> None:
        self.commands.append(command)

    def get_connect_credentials(self):
        return SimpleNamespace(url="http://localhost:45678", token="connect-tok")


class TestSQLV2EnsureServer(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, short_id="nbens01")
        self.sandbox = _RecordingSandbox()

    def _create_runtime(self, server_url: str | None = None) -> KernelRuntime:
        return KernelRuntime.objects.create(
            team=self.team,
            notebook=self.notebook,
            notebook_short_id=self.notebook.short_id,
            user=self.user,
            status=KernelRuntime.Status.RUNNING,
            backend=KernelRuntime.Backend.DOCKER,
            sandbox_id="sbx-1",
            server_url=server_url or "",
        )

    def _ensure(self, reported_version: str | None):
        sandbox_class = SimpleNamespace(get_by_id=lambda _id: self.sandbox)
        with (
            patch("products.notebooks.backend.sql_v2._server_version", return_value=reported_version),
            patch("products.notebooks.backend.sql_v2.get_sandbox_class_for_backend", return_value=sandbox_class),
            patch("products.notebooks.backend.sql_v2._wait_for_server_ready"),
        ):
            return ensure_sql_v2_server(self.notebook, self.user)

    def test_current_server_is_reused_without_control_plane_calls(self):
        # A redeploy on every run would restart the server and wipe the result cache.
        runtime = self._create_runtime(server_url="http://localhost:1")
        result = self._ensure(reported_version=kernel_package_bytes_and_hash()[1])
        self.assertEqual(result.id, runtime.id)
        self.assertEqual(self.sandbox.commands, [])
        self.assertEqual(self.sandbox.files, {})

    def test_stale_server_is_redeployed(self):
        # Missing this redeploy strands sandboxes on old kernel code (e.g. no /page route).
        runtime = self._create_runtime(server_url="http://localhost:1")
        result = self._ensure(reported_version="some-old-version")
        package, _version = kernel_package_bytes_and_hash()
        self.assertEqual(self.sandbox.files["/tmp/nb_kernel.tar.gz"], package)
        self.assertEqual(self.sandbox.files["/tmp/nb_sql_v2_secret"], kernel_server_secret(str(runtime.id)).encode())
        self.assertEqual(len(self.sandbox.commands), 1)
        self.assertEqual(result.server_url, "http://localhost:45678")
        self.assertEqual(result.server_connect_token, "connect-tok")

    def test_launch_command_shape_regressions(self):
        # Two bugs shipped from this one string: pkill -f of our own module name matches
        # the launch command's shell and kills the deploy; and backgrounding a compound
        # command records a wrapper subshell PID so later redeploys kill nothing.
        self._create_runtime(server_url="http://localhost:1")
        self._ensure(reported_version="some-old-version")
        launch = self.sandbox.commands[0]
        self.assertNotRegex(launch, r"pkill[^;&]*[^\[]nb_kernel")
        self.assertIn("echo $! > /tmp/nb_kernel_server.pid", launch)
        # The backgrounded segment must be a single simple command (no cd &&-chain).
        backgrounded = launch.rsplit(";", 1)[-1].split("&")[0]
        self.assertNotIn("&&", backgrounded)
        self.assertIn("nb_kernel.server", backgrounded)

    def test_no_running_runtime_raises(self):
        with self.assertRaises(SQLV2KernelNotRunning):
            self._ensure(reported_version=None)


class TestSQLV2RunPage(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, short_id="nbpage1")

    def _create_run(
        self,
        status=NotebookNodeRun.Status.DONE,
        node_id="n1",
        code="select 1",
        node_type=NotebookNodeRun.NodeType.HOGQL,
        result_id=None,
    ) -> NotebookNodeRun:
        with team_scope(self.team.id):
            return NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                node_id=node_id,
                status=status,
                code=code,
                node_type=node_type,
                result_id=result_id,
            )

    def _get(self, run_id: str, offset=50, limit=50):
        return self.client.get(
            f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/sql_v2/runs/{run_id}/page/",
            {"offset": offset, "limit": limit},
        )

    @patch("products.notebooks.backend.presentation.views.notebook.fetch_sql_v2_page")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_returns_page_from_kernel(self, _mock_enabled, mock_fetch):
        mock_fetch.return_value = {"columns": ["a"], "types": [["a", "Int64"]], "rows": [[51]], "has_more": False}
        run = self._create_run()
        response = self._get(str(run.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rows"], [[51]])
        self.assertEqual(mock_fetch.call_args.kwargs["offset"], 50)
        self.assertEqual(mock_fetch.call_args.kwargs["limit"], 50)

    @patch("products.notebooks.backend.presentation.views.notebook.fetch_sql_v2_page")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_stale_run_is_rejected(self, _mock_enabled, mock_fetch):
        # A newer completed run supersedes this result — paging it would mix two executions.
        old_run = self._create_run()
        self._create_run()  # newer DONE run for the same node
        response = self._get(str(old_run.id))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "stale")
        mock_fetch.assert_not_called()

    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_kernel_not_running_returns_503(self, _mock_enabled):
        # No KernelRuntime exists, so the real fetch path raises SQLV2KernelNotRunning.
        run = self._create_run()
        response = self._get(str(run.id))
        self.assertEqual(response.status_code, 503)

    @patch("products.notebooks.backend.presentation.views.notebook.fetch_sql_v2_page")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_empty_code_run_is_rejected_before_reaching_the_kernel(self, _mock_enabled, mock_fetch):
        # Pre-migration runs stored code="" — paging must fail clearly, not round-trip to an opaque error.
        run = self._create_run(code="")
        response = self._get(str(run.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn("re-run", response.json()["detail"])
        mock_fetch.assert_not_called()

    @patch("products.notebooks.backend.presentation.views.notebook.fetch_sql_v2_page")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_kernel_run_without_result_frame_is_rejected_before_reaching_the_kernel(self, _mock_enabled, mock_fetch):
        # A python/duckdb run pages by its result frame; no result_id means nothing to slice.
        run = self._create_run(code="df1.head()", node_type=NotebookNodeRun.NodeType.PYTHON, result_id=None)
        response = self._get(str(run.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn("re-run", response.json()["detail"])
        mock_fetch.assert_not_called()

    @parameterized.expand(
        [
            ("running_run", NotebookNodeRun.Status.RUNNING, 400),
            ("failed_run", NotebookNodeRun.Status.FAILED, 400),
        ]
    )
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_non_done_run_is_rejected(self, _name, status, expected, _mock_enabled):
        run = self._create_run(status=status)
        self.assertEqual(self._get(str(run.id)).status_code, expected)

    @patch("products.notebooks.backend.presentation.views.notebook.fetch_sql_v2_page")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_query_restricted_member_cannot_page(self, _mock_enabled, mock_fetch):
        # Paging returns analytics rows, so a query-denied notebook reader must not fetch pages.
        run = self._create_run()
        _restrict_query_access(self)
        self.assertEqual(self._get(str(run.id)).status_code, 403)
        mock_fetch.assert_not_called()

    @patch("products.notebooks.backend.presentation.views.notebook.fetch_sql_v2_page")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_one_in_flight_page_fetch_per_user(self, _mock_enabled, mock_fetch):
        # Each out-of-cache page fetch holds a web worker for up to the kernel timeout, so a
        # user with a fetch already in flight must be rejected instead of stacking workers.
        mock_fetch.return_value = {"columns": [], "types": [], "rows": [], "has_more": False}
        run = self._create_run()
        lock_key = sql_v2_page_lock_key(self.team.id, self.user.id)
        cache.add(lock_key, True, timeout=10)
        try:
            response = self._get(str(run.id))
            self.assertEqual(response.status_code, 429)
            mock_fetch.assert_not_called()
        finally:
            cache.delete(lock_key)
        # A finished fetch releases the lock, so back-to-back sequential pages keep working.
        self.assertEqual(self._get(str(run.id)).status_code, 200)
        self.assertEqual(self._get(str(run.id)).status_code, 200)


class TestSQLV2PageDispatch(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, short_id="nbpgd01")
        with team_scope(self.team.id):
            self.node_run = NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                node_id="n1",
                status=NotebookNodeRun.Status.DONE,
                code="select event from events",
            )

    def _create_runtime(self) -> KernelRuntime:
        return KernelRuntime.objects.create(
            team=self.team,
            notebook=self.notebook,
            notebook_short_id=self.notebook.short_id,
            user=self.user,
            status=KernelRuntime.Status.RUNNING,
            backend=KernelRuntime.Backend.DOCKER,
            sandbox_id="sbx-1",
            server_url="http://localhost:12345",
            server_connect_token="connect-tok",
        )

    def test_raises_without_running_kernel(self):
        with self.assertRaises(SQLV2KernelNotRunning):
            fetch_sql_v2_page(self.notebook, self.user, self.node_run, offset=50, limit=50)

    @patch("products.notebooks.backend.sql_v2.requests.post")
    def test_posts_run_code_and_paging_to_kernel(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"columns": [], "types": [], "rows": [], "has_more": False}
        runtime = self._create_runtime()
        fetch_sql_v2_page(self.notebook, self.user, self.node_run, offset=100, limit=25)
        self.assertIn("/page", mock_post.call_args.args[0])
        # Credentials ride headers, never the URL — a query-string token lands in access logs.
        self.assertNotIn("?", mock_post.call_args.args[0])
        headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer connect-tok")
        self.assertTrue(
            kernel_auth.verify_command_token(
                kernel_server_secret(str(runtime.id)), str(self.node_run.id), headers["X-Command-Token"]
            )
        )
        payload = mock_post.call_args.kwargs["json"]
        # The kernel must page the code that produced the result, not whatever the editor holds now.
        self.assertEqual(payload["code"], "select event from events")
        self.assertEqual((payload["offset"], payload["limit"]), (100, 25))

    @patch("products.notebooks.backend.sql_v2.requests.post")
    def test_kernel_run_pages_by_result_id_not_code(self, mock_post):
        # A python/duckdb result pages by slicing its on-sandbox frame; its code is not a HogQL
        # query, so it must never reach the data plane as one.
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"columns": [], "types": [], "rows": [], "has_more": False}
        self._create_runtime()
        with team_scope(self.team.id):
            kernel_run = NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                node_id="py1",
                status=NotebookNodeRun.Status.DONE,
                code="df1.head()",
                node_type=NotebookNodeRun.NodeType.PYTHON,
                result_id="6f8ec2f4-3f42-4b0e-9a2e-5f5b1c9d0a11",
            )
        fetch_sql_v2_page(self.notebook, self.user, kernel_run, offset=50, limit=50)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["result_id"], "6f8ec2f4-3f42-4b0e-9a2e-5f5b1c9d0a11")
        self.assertNotIn("code", payload)
        self.assertNotIn("data_plane_token", payload)

    @parameterized.expand(
        [
            ("outdated_kernel_404", 404, None, SQLV2KernelNotRunning),
            # Token expiry / kernel redeploy — a re-run reissues the token, so it's "re-run" (503), not a query error.
            ("stale_token_401", 401, None, SQLV2KernelNotRunning),
            ("forbidden_403", 403, None, SQLV2KernelNotRunning),
            ("query_error_400", 400, {"error": "no such column"}, SQLV2PageError),
            # Any other non-200 is infrastructure, not a bad query.
            ("kernel_error_500", 500, None, SQLV2KernelNotRunning),
        ]
    )
    @patch("products.notebooks.backend.sql_v2.requests.post")
    def test_kernel_error_statuses_map_to_exceptions(self, _name, status_code, body, expected_exception, mock_post):
        mock_post.return_value.status_code = status_code
        mock_post.return_value.json.return_value = body
        self._create_runtime()
        with self.assertRaises(expected_exception):
            fetch_sql_v2_page(self.notebook, self.user, self.node_run, offset=0, limit=50)


class TestSQLV2RunResult(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, short_id="nbres01")

    def _url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/sql_v2/runs/{run_id}/"

    def _create_run(self, status, envelope=None, error="") -> NotebookNodeRun:
        with team_scope(self.team.id):
            return NotebookNodeRun.objects.create(
                team=self.team, notebook=self.notebook, node_id="n1", status=status, envelope=envelope, error=error
            )

    @parameterized.expand(
        [
            (NotebookNodeRun.Status.RUNNING, None, "", None, None),
            (NotebookNodeRun.Status.DONE, {"first_page": [[42]]}, "", {"first_page": [[42]]}, None),
            (NotebookNodeRun.Status.FAILED, None, "boom", None, "boom"),
            # An interrupted run keeps its envelope: the captured stdout/stderr must reach the UI.
            (
                NotebookNodeRun.Status.INTERRUPTED,
                {"stdout": "partial"},
                "Run interrupted.",
                {"stdout": "partial"},
                "Run interrupted.",
            ),
        ]
    )
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_result_shape_by_status(self, status, envelope, error, expected_result, expected_error, _mock_enabled):
        run = self._create_run(status, envelope=envelope, error=error)
        response = self.client.get(self._url(str(run.id)))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], status)
        # result is surfaced when done or interrupted; error when failed or interrupted
        self.assertEqual(body["result"], expected_result)
        self.assertEqual(body["error"], expected_error)

    @parameterized.expand([("00000000-0000-0000-0000-000000000000",), ("not-a-uuid",)])
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_missing_or_malformed_run_returns_404(self, run_id, _mock_enabled):
        self.assertEqual(self.client.get(self._url(run_id)).status_code, 404)

    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_run_from_another_notebook_is_not_readable(self, _mock_enabled):
        # IDOR guard: a run belonging to a different notebook in the same team must not be
        # fetchable through this notebook's endpoint, even with a valid run_id.
        other_notebook = Notebook.objects.create(team=self.team, short_id="nbres02")
        with team_scope(self.team.id):
            other_run = NotebookNodeRun.objects.create(
                team=self.team, notebook=other_notebook, node_id="n1", status=NotebookNodeRun.Status.DONE
            )
        self.assertEqual(self.client.get(self._url(str(other_run.id))).status_code, 404)

    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_query_restricted_member_cannot_read_result(self, _mock_enabled):
        # The result envelope is analytics rows, so a query-denied notebook reader must not read them back.
        run = self._create_run(NotebookNodeRun.Status.DONE, envelope={"first_page": [[42]]})
        _restrict_query_access(self)
        self.assertEqual(self.client.get(self._url(str(run.id))).status_code, 403)


class TestSQLV2RunInterrupt(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, short_id="nbint01")
        with team_scope(self.team.id):
            self.node_run = NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                node_id="n1",
                status=NotebookNodeRun.Status.RUNNING,
                code="select event from events",
            )

    def _url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/sql_v2/runs/{run_id}/interrupt/"

    def _create_runtime(self, user=None) -> KernelRuntime:
        return KernelRuntime.objects.create(
            team=self.team,
            notebook=self.notebook,
            notebook_short_id=self.notebook.short_id,
            user=user or self.user,
            status=KernelRuntime.Status.RUNNING,
            backend=KernelRuntime.Backend.DOCKER,
            sandbox_id="sbx-1",
            server_url="http://localhost:12345",
            server_connect_token="connect-tok",
        )

    def _reload_run(self) -> NotebookNodeRun:
        return NotebookNodeRun.objects.for_team(self.team.id).get(id=self.node_run.id)

    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    @patch("products.notebooks.backend.sql_v2.requests.post")
    def test_interrupt_posts_run_scoped_command_to_kernel(self, mock_post, _mock_enabled):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"interrupted": True, "known": True}
        runtime = self._create_runtime()

        response = self.client.post(self._url(str(self.node_run.id)))

        self.assertEqual(response.status_code, 202)
        self.assertIn("/interrupt", mock_post.call_args.args[0])
        headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer connect-tok")
        self.assertTrue(
            kernel_auth.verify_command_token(
                kernel_server_secret(str(runtime.id)), str(self.node_run.id), headers["X-Command-Token"]
            )
        )
        # The terminal state must come from the sandbox's callback, not from this endpoint.
        self.assertEqual(self._reload_run().status, NotebookNodeRun.Status.RUNNING)

    @parameterized.expand(
        [
            (NotebookNodeRun.Status.DONE,),
            (NotebookNodeRun.Status.FAILED,),
            (NotebookNodeRun.Status.INTERRUPTED,),
        ]
    )
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    @patch("products.notebooks.backend.sql_v2.requests.post")
    def test_interrupt_of_terminal_run_never_reaches_the_kernel(self, status, mock_post, _mock_enabled):
        self._create_runtime()
        self.node_run.status = status
        self.node_run.save(update_fields=["status"])

        response = self.client.post(self._url(str(self.node_run.id)))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], status)
        mock_post.assert_not_called()
        self.assertEqual(self._reload_run().status, status)

    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_unreachable_kernel_marks_run_interrupted(self, _mock_enabled):
        # No kernel means the callback can never arrive; interrupt is the user's escape
        # hatch out of a RUNNING-forever row.
        response = self.client.post(self._url(str(self.node_run.id)))

        self.assertEqual(response.status_code, 200)
        run = self._reload_run()
        self.assertEqual(run.status, NotebookNodeRun.Status.INTERRUPTED)
        self.assertTrue(run.error)

    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_run_on_a_collaborators_kernel_is_not_marked_terminal(self, _mock_enabled):
        # Kernels are per user: another editor's kernel may still be executing this run, so
        # the requester's unreachable-kernel path must not falsely terminate a live run.
        other_user = self._create_user("collaborator@posthog.com")
        self._create_runtime(user=other_user)

        response = self.client.post(self._url(str(self.node_run.id)))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._reload_run().status, NotebookNodeRun.Status.RUNNING)

    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    @patch("products.notebooks.backend.sql_v2.requests.post")
    def test_run_unknown_to_the_kernel_stays_running(self, mock_post, _mock_enabled):
        # Dispatch may still be in flight (Temporal): nothing was stopped, so the run must
        # not be marked terminal and the client is told to retry.
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"interrupted": False, "known": False}
        self._create_runtime()

        response = self.client.post(self._url(str(self.node_run.id)))

        self.assertEqual(response.status_code, 202)
        self.assertIn("detail", response.json())
        self.assertEqual(self._reload_run().status, NotebookNodeRun.Status.RUNNING)

    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_run_from_another_notebook_is_404(self, _mock_enabled):
        # IDOR guard: a run id from a different notebook must not be interruptible (or even
        # discoverable) through this notebook's endpoint.
        other_notebook = Notebook.objects.create(team=self.team, short_id="nbint02")
        with team_scope(self.team.id):
            other_run = NotebookNodeRun.objects.create(
                team=self.team, notebook=other_notebook, node_id="n1", status=NotebookNodeRun.Status.RUNNING
            )
        response = self.client.post(self._url(str(other_run.id)))
        self.assertEqual(response.status_code, 404)
        reloaded = NotebookNodeRun.objects.for_team(self.team.id).get(id=other_run.id)
        self.assertEqual(reloaded.status, NotebookNodeRun.Status.RUNNING)


class TestSQLV2Activities(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, short_id="nbact01")

    def _create_run(self) -> NotebookNodeRun:
        with team_scope(self.team.id):
            return NotebookNodeRun.objects.create(
                team=self.team, notebook=self.notebook, node_id="n1", status=NotebookNodeRun.Status.RUNNING
            )

    def _run_input(self, run: NotebookNodeRun) -> SQLV2RunInput:
        return SQLV2RunInput(
            run_id=str(run.id),
            notebook_short_id=self.notebook.short_id,
            team_id=self.team.id,
            user_id=self.user.id,
            code="select 1",
        )

    def _reload(self, run: NotebookNodeRun) -> NotebookNodeRun:
        return NotebookNodeRun.objects.for_team(self.team.id).get(id=run.id)

    def test_dispatch_activity_marks_failed_without_kernel(self):
        run = self._create_run()
        dispatch_sql_v2_run_activity(self._run_input(run))
        self.assertEqual(self._reload(run).status, NotebookNodeRun.Status.FAILED)

    @patch("products.notebooks.backend.sql_v2._server_version")
    @patch("products.notebooks.backend.sql_v2.requests.post")
    def test_dispatch_activity_posts_to_ready_server(self, mock_post, mock_version):
        mock_version.return_value = kernel_package_bytes_and_hash()[1]  # server already at the deployed version
        run = self._create_run()
        runtime = KernelRuntime.objects.create(
            team=self.team,
            notebook=self.notebook,
            notebook_short_id=self.notebook.short_id,
            user=self.user,
            status=KernelRuntime.Status.RUNNING,
            backend=KernelRuntime.Backend.DOCKER,
            sandbox_id="sbx-1",
            server_url="http://localhost:12345",
            server_connect_token="connect-tok",
        )
        dispatch_sql_v2_run_activity(self._run_input(run))
        mock_post.assert_called_once()
        self.assertIn("/run", mock_post.call_args.args[0])
        # Credentials ride headers, never the URL — a query-string token lands in access logs.
        self.assertNotIn("?", mock_post.call_args.args[0])
        headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer connect-tok")
        self.assertTrue(
            kernel_auth.verify_command_token(
                kernel_server_secret(str(runtime.id)), str(run.id), headers["X-Command-Token"]
            )
        )
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["code"], "select 1")
        # Dropping cache_limit silently degrades every page fetch into a ClickHouse re-query.
        self.assertGreater(payload["cache_limit"], payload["page_limit"])
        # The kernel needs both legs to complete a run: the data plane to fetch, the callback to report.
        short_id, team_id, _user_id = verify_data_plane_token(payload["data_plane_token"])
        self.assertEqual((short_id, team_id), (self.notebook.short_id, self.team.id))
        self.assertIn("/internal/notebooks/data_plane/query/", payload["data_plane_url"])
        self.assertEqual(self._reload(run).status, NotebookNodeRun.Status.RUNNING)

    def test_mark_failed_activity(self):
        run = self._create_run()
        mark_sql_v2_run_failed_activity(self._run_input(run))
        self.assertEqual(self._reload(run).status, NotebookNodeRun.Status.FAILED)


class TestSQLV2CommandToken(SimpleTestCase):
    # Backend mints (sql_v2), the in-sandbox kernel verifies (kernel.auth) — this
    # round-trip is the contract that keeps the two HMAC implementations in sync.
    def test_valid_token_verifies(self):
        secret = kernel_server_secret("rt-1")
        self.assertTrue(kernel_auth.verify_command_token(secret, "run-1", mint_command_token(secret, "run-1")))

    @parameterized.expand(
        [
            ("wrong_run_id", lambda s: (s, "run-2", mint_command_token(s, "run-1"))),
            ("wrong_secret", lambda s: (kernel_server_secret("rt-2"), "run-1", mint_command_token(s, "run-1"))),
            ("tampered_signature", lambda s: (s, "run-1", mint_command_token(s, "run-1")[:-1] + "x")),
            ("expired", lambda s: (s, "run-1", mint_command_token(s, "run-1", ttl_seconds=-1))),
            ("garbage", lambda s: (s, "run-1", "not-a-token")),
        ]
    )
    def test_invalid_tokens_rejected(self, _name, make_case):
        verify_secret, run_id, token = make_case(kernel_server_secret("rt-1"))
        self.assertFalse(kernel_auth.verify_command_token(verify_secret, run_id, token))


class TestSQLV2DataPlaneToken(SimpleTestCase):
    def test_round_trip(self):
        token = mint_data_plane_token("nb123", 7, 42)
        self.assertEqual(verify_data_plane_token(token), ("nb123", 7, 42))

    @parameterized.expand(
        [
            ("tampered", lambda: mint_data_plane_token("nb123", 7, 42)[:-2] + "xx"),
            ("wrong_salt", lambda: mint_callback_token("run-1", 7)),
            ("garbage", lambda: "not-a-token"),
        ]
    )
    def test_invalid_tokens_rejected(self, _name, make_token):
        with self.assertRaises(signing.BadSignature):
            verify_data_plane_token(make_token())


class TestSQLV2DataPlaneEndpoint(APIBaseTest):
    URL = "/internal/notebooks/data_plane/query/"

    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, short_id="nbdp001")

    def _post(self, body: dict, token: str | None = None):
        kwargs: dict[str, Any] = {"data": json.dumps(body), "content_type": "application/json"}
        if token is not None:
            kwargs["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return self.client.post(self.URL, **kwargs)

    def _token(self, short_id: str | None = None) -> str:
        return mint_data_plane_token(short_id or self.notebook.short_id, self.team.id, self.user.id)

    def _get_status(self, query_id: str, token: str | None = None):
        return self.client.get(
            f"{self.URL}{query_id}/",
            HTTP_AUTHORIZATION=f"Bearer {token or self._token()}",
        )

    def _run_to_completion(self, body: dict):
        # Celery is eager in tests, so the enqueue executes inline and the first
        # status poll is already terminal — the same protocol the kernel follows.
        response = self._post(body, token=self._token())
        self.assertEqual(response.status_code, 202, response.content)
        query_id = response.json()["query_id"]
        return self._get_status(query_id)

    def test_runs_query_and_returns_arrow(self):
        response = self._run_to_completion({"query": "select 1 as answer"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Content-Type"], "application/vnd.apache.arrow.stream")
        columns, rows, types = decode_arrow_stream(response.content)
        self.assertEqual(columns, ["answer"])
        self.assertEqual(rows, [(1,)])
        # The real ClickHouse type must survive the Arrow round-trip (schema metadata).
        self.assertEqual(types[0][0], "answer")
        self.assertIn("Int", types[0][1])

    def test_outer_limit_and_offset_cap_the_page(self):
        response = self._run_to_completion({"query": "select number from numbers(10)", "limit": 3, "offset": 2})
        self.assertEqual(response.status_code, 200, response.content)
        _columns, rows, _types = decode_arrow_stream(response.content)
        self.assertEqual(rows, [(2,), (3,), (4,)])

    def test_materialization_request_is_accepted_and_clipped_at_the_row_ceiling(self):
        # The kernel executor fetches whole frames with limit=_MATERIALIZE_ROW_CAP (2M, not
        # importable here: the executor module needs jupyter_client). The serializer must
        # accept that limit (it once capped at 1000, 400-ing every materialization), and the
        # async limit context then clips the frame at MAX_SELECT_RETURNED_ROWS (50k) — a
        # deliberate bound until the object-storage frame store (sql_v2_frame_store.md)
        # gives big frames a transport that doesn't round-trip through Redis.
        response = self._run_to_completion({"query": "select number from numbers(50001)", "limit": 2_000_000})
        self.assertEqual(response.status_code, 200, response.content)
        _columns, rows, _types = decode_arrow_stream(response.content)
        self.assertEqual(len(rows), 50_000)

    def test_execution_error_surfaces_through_status(self):
        # Valid syntax but fails at execution — the error must reach the sandbox via the poll.
        response = self._run_to_completion({"query": "select nonexistent_column from events"})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertTrue(response.json()["error"])

    def test_status_rejects_bad_auth_and_unknown_query(self):
        self.assertEqual(self.client.get(f"{self.URL}deadbeef/").status_code, 401)
        self.assertEqual(self._get_status("deadbeef").status_code, 404)

    def test_status_is_team_scoped(self):
        # A leaked query_id plus a token for another team must not read the result.
        response = self._post({"query": "select 1"}, token=self._token())
        query_id = response.json()["query_id"]
        other_team_token = mint_data_plane_token(self.notebook.short_id, self.team.id + 999, None)
        self.assertEqual(self._get_status(query_id, token=other_team_token).status_code, 404)

    def test_hogql_error_is_surfaced(self):
        response = self._post({"query": "select ceci n'est pas une query"}, token=self._token())
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()["error"])

    @parameterized.expand(
        [
            ("missing_token", None, 401),
            ("garbage_token", "not-a-token", 401),
        ]
    )
    def test_rejects_bad_auth(self, _name, token, expected_status):
        response = self._post({"query": "select 1"}, token=token)
        self.assertEqual(response.status_code, expected_status)

    def test_unknown_notebook_returns_404(self):
        response = self._post({"query": "select 1"}, token=self._token(short_id="nope999"))
        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            # The wrapper nests the user's query as a subquery; these are the shapes
            # that break naive wrapping (inner LIMIT interacting with the outer one,
            # set queries that must stay parenthesized, and a trailing line comment that
            # would swallow the wrapper's closing paren without the newline).
            ("inner_limit_caps_before_outer", "select number from numbers(10) limit 4", 3, 2, [(2,), (3,)]),
            ("union_set_query", "select 1 as n union all select 2 as n", 10, 0, [(1,), (2,)]),
            ("trailing_line_comment", "select 1 as n -- top events", 10, 0, [(1,)]),
        ]
    )
    def test_query_shapes_survive_the_wrapper(self, _name, query, limit, offset, expected_rows):
        response = self._run_to_completion({"query": query, "limit": limit, "offset": offset})
        self.assertEqual(response.status_code, 200, response.content)
        _columns, rows, _types = decode_arrow_stream(response.content)
        self.assertEqual(sorted(rows), expected_rows)


class TestSQLV2RunContract(APIBaseTest):
    def test_dispatch_payload_drives_the_kernel_and_its_callback_round_trips(self):
        # Closes the seams the unit tests can't see: the dispatch payload's keys must
        # match what the kernel runner reads, the runner's envelope must satisfy the
        # callback serializer, and the callback token/URL minted at dispatch must be
        # accepted by the callback endpoint. A renamed payload or envelope key passes
        # every per-component test and breaks only here.
        notebook = Notebook.objects.create(team=self.team, short_id="nbctr01")
        with team_scope(self.team.id):
            run = NotebookNodeRun.objects.create(
                team=self.team,
                notebook=notebook,
                node_id="n1",
                status=NotebookNodeRun.Status.RUNNING,
                code="select 1",
            )
        KernelRuntime.objects.create(
            team=self.team,
            notebook=notebook,
            notebook_short_id=notebook.short_id,
            user=self.user,
            status=KernelRuntime.Status.RUNNING,
            backend=KernelRuntime.Backend.DOCKER,
            sandbox_id="sbx-1",
            server_url="http://localhost:1",
        )

        with (
            patch(
                "products.notebooks.backend.sql_v2._server_version",
                return_value=kernel_package_bytes_and_hash()[1],
            ),
            patch("products.notebooks.backend.sql_v2.requests.post") as mock_post,
        ):
            dispatch_sql_v2_run(notebook, self.user, run, "select 1")
        payload = mock_post.call_args.kwargs["json"]

        delivered: dict = {}
        with (
            patch(
                "products.notebooks.backend.sandbox.kernel.data_plane.fetch_query_page",
                return_value=(["a"], [(1,)], [["a", "Int64"]]),
            ),
            patch.object(
                kernel_runner,
                "_post_callback",
                side_effect=lambda url, token, env: delivered.update({"url": url, "envelope": env}),
            ),
        ):
            kernel_runner.execute_run(payload)

        self.assertTrue(delivered["url"].endswith(f"/internal/notebooks/runs/{run.id}/result/"))
        response = self.client.post(
            f"/internal/notebooks/runs/{run.id}/result/",
            data=json.dumps({"envelope": delivered["envelope"]}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {payload['callback_token']}",
        )
        self.assertEqual(response.status_code, 200, response.content)
        stored = NotebookNodeRun.objects.for_team(self.team.id).get(id=run.id)
        self.assertEqual(stored.status, NotebookNodeRun.Status.DONE)
        self.assertEqual(stored.envelope["first_page"], [[1]])
        self.assertEqual(stored.envelope["types"], [["a", "Int64"]])


class TestSQLV2KernelServerHTTP(SimpleTestCase):
    # The kernel HTTP layer (routing, auth wiring, async-run vs sync-page split) has no
    # other CI coverage — it only runs inside the sandbox. Loopback-only, stubbed runner.
    def test_routes_auth_and_dispatch(self):
        from products.notebooks.backend.sandbox.kernel import server as kernel_server

        original_config = dict(kernel_server._config)
        kernel_server._config.update({"secret": "test-secret", "version": "vtest"})
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), kernel_server.KernelServerHandler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def post(path: str, token: str, token_header: str = "X-Command-Token"):
            # X-Command-Token is the primary transport; Authorization stays a fallback for
            # backends that predate the split (Authorization now carries Modal tunnel auth).
            token_value = f"Bearer {token}" if token_header == "Authorization" else token
            request = urllib.request.Request(
                f"{base}{path}",
                data=json.dumps({"run_id": "run-1"}).encode(),
                headers={token_header: token_value, "Content-Type": "application/json"},
                method="POST",
            )
            return urllib.request.urlopen(request, timeout=5)

        token = mint_command_token("test-secret", "run-1")
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=5) as response:
                self.assertEqual(json.loads(response.read())["version"], "vtest")

            with self.assertRaises(urllib.error.HTTPError) as forged:
                post("/run", token="forged")
            self.assertEqual(forged.exception.code, 401)

            ran = threading.Event()
            with patch.object(kernel_server, "execute_run", side_effect=lambda _p: ran.set()):
                with post("/run", token=token) as response:
                    self.assertEqual(response.status, 202)
                self.assertTrue(ran.wait(5))  # the run must execute off the request thread

            # An older backend sends the command token as a bearer Authorization — the
            # fallback must keep verifying it while mixed versions roll out.
            ran.clear()
            with patch.object(kernel_server, "execute_run", side_effect=lambda _p: ran.set()):
                with post("/run", token=token, token_header="Authorization") as response:
                    self.assertEqual(response.status, 202)
                self.assertTrue(ran.wait(5))

            page = {"columns": ["a"], "types": [], "rows": [[1]], "has_more": False}
            with patch.object(kernel_server, "fetch_page", return_value=page):
                with post("/page", token=token) as response:
                    self.assertEqual(response.status, 200)  # pages are synchronous
                    self.assertEqual(json.loads(response.read())["rows"], [[1]])

            # /interrupt is run-scoped: the handler passes the payload's run_id through and
            # reports whether the run was known, so the backend can distinguish a delivered
            # interrupt from a noop.
            with patch.object(kernel_server, "request_interrupt", return_value=False) as mock_interrupt:
                with post("/interrupt", token=token) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())["known"], False)
                mock_interrupt.assert_called_once_with("run-1")

            with self.assertRaises(urllib.error.HTTPError) as unknown:
                post("/nope", token=token)
            self.assertEqual(unknown.exception.code, 404)
        finally:
            httpd.shutdown()
            httpd.server_close()
            kernel_server._config.clear()
            kernel_server._config.update(original_config)


class TestSQLV2KernelPackage(SimpleTestCase):
    def test_arrow_contract_round_trip(self):
        # Where backend encoding and kernel decoding actually meet: duplicate column
        # names must survive, a mixed-type column falls back to strings, and the
        # declared HogQL types ride through as schema metadata.
        columns = ["value", "value", "mixed"]
        rows = [(1, "a", 1), (2, "b", "two")]
        types = [["value", "Int64"], ["value", "String"], ["mixed", "String"]]
        decoded_columns, decoded_rows, decoded_types = decode_arrow_stream(_rows_to_arrow_bytes(columns, rows, types))
        self.assertEqual(decoded_columns, columns)
        self.assertEqual(decoded_rows, [(1, "a", "1"), (2, "b", "two")])
        self.assertEqual(decoded_types, types)

    def test_types_fall_back_to_arrow_schema_without_metadata(self):
        columns, rows = ["n", "s"], [(1, "a")]
        _cols, _rows, types = decode_arrow_stream(_rows_to_arrow_bytes(columns, rows))
        self.assertEqual(types, [["n", "Int64"], ["s", "String"]])

    def test_envelope_cells_are_json_safe(self):
        result = kernel_envelope.from_columns_and_rows(
            ["ts", "nan", "blob"],
            [(datetime.datetime(2026, 7, 3, 12, 0), math.nan, b"bytes")],
        )
        json.dumps(result)  # a NaN or datetime here would make the callback body unparseable
        self.assertEqual(result["first_page"], [["2026-07-03T12:00:00", None, "bytes"]])
        self.assertEqual(result["row_count"], 1)

    def test_runner_delivers_error_callback_when_fetch_fails(self):
        # A failed fetch must still produce a callback — otherwise the run hangs until the watchdog.
        payload = {
            "run_id": "r1",
            "code": "select 1",
            "callback_url": "http://backend/cb",
            "callback_token": "cbt",
            "data_plane_url": "http://backend/dp",
            "data_plane_token": "dpt",
        }
        delivered = {}
        with (
            patch.object(kernel_runner, "_post_callback", side_effect=lambda url, token, env: delivered.update(env)),
            patch(
                "products.notebooks.backend.sandbox.kernel.data_plane.fetch_query_page",
                side_effect=DataPlaneError("no such table"),
            ),
        ):
            kernel_runner.execute_run(payload)
        self.assertEqual(delivered["status"], "error")
        self.assertEqual(delivered["error"], "no such table")

    def _run_and_cache(self, run_id: str, rows_returned: int, cache_limit: int = 300):
        payload = {
            "run_id": run_id,
            "code": "select 1",
            "callback_url": "http://backend/cb",
            "callback_token": "t",
            "data_plane_url": "u",
            "data_plane_token": "t",
            "page_limit": 50,
            "cache_limit": cache_limit,
        }
        mock_fetch = patch(
            "products.notebooks.backend.sandbox.kernel.data_plane.fetch_query_page",
            return_value=(["n"], [(i,) for i in range(rows_returned)], [["n", "Int64"]]),
        )
        with mock_fetch as fetch:
            result = kernel_runner._build_envelope(payload)
        return payload, result, fetch

    def test_pages_within_the_cache_never_requery(self):
        # The whole point of the cache: paging must not re-run the query on ClickHouse.
        payload, result, _ = self._run_and_cache("r-cache-1", rows_returned=301)
        self.assertEqual(len(result["first_page"]), 50)
        self.assertTrue(result["has_more"])
        with patch("products.notebooks.backend.sandbox.kernel.data_plane.fetch_query_page") as fetch:
            page = kernel_runner.fetch_page({**payload, "offset": 250, "limit": 50})
        fetch.assert_not_called()
        self.assertEqual(page["rows"][0], [250])
        self.assertEqual(len(page["rows"]), 50)
        self.assertTrue(page["has_more"])  # cache is incomplete — more rows exist beyond it

    def test_page_beyond_incomplete_cache_falls_back_to_requery(self):
        payload, _result, _ = self._run_and_cache("r-cache-2", rows_returned=301)
        with patch(
            "products.notebooks.backend.sandbox.kernel.data_plane.fetch_query_page",
            return_value=(["n"], [(i,) for i in range(10)], [["n", "Int64"]]),
        ) as fetch:
            kernel_runner.fetch_page({**payload, "offset": 290, "limit": 50})
        self.assertEqual(fetch.call_args.kwargs["offset"], 290)

    def test_complete_cache_reports_no_more_rows(self):
        payload, result, _ = self._run_and_cache("r-cache-3", rows_returned=120)
        self.assertTrue(result["has_more"])  # 120 rows > the 50-row first page
        with patch("products.notebooks.backend.sandbox.kernel.data_plane.fetch_query_page") as fetch:
            page = kernel_runner.fetch_page({**payload, "offset": 100, "limit": 50})
        fetch.assert_not_called()
        self.assertEqual(len(page["rows"]), 20)
        self.assertFalse(page["has_more"])

    @parameterized.expand(
        [
            ("more_rows_exist", 6, True, 5),  # limit+1 rows came back → has_more, trimmed to limit
            ("exact_page", 5, False, 5),
            ("short_page", 2, False, 2),
        ]
    )
    def test_fetch_page_has_more_via_limit_plus_one(self, _name, rows_returned, expected_has_more, expected_rows):
        payload = {"code": "select 1", "data_plane_url": "u", "data_plane_token": "t", "offset": 10, "limit": 5}
        with patch(
            "products.notebooks.backend.sandbox.kernel.data_plane.fetch_query_page",
            return_value=(["n"], [(i,) for i in range(rows_returned)], [["n", "Int64"]]),
        ) as mock_fetch:
            page = kernel_runner.fetch_page(payload)
        self.assertEqual(mock_fetch.call_args.kwargs["limit"], 6)  # fetches limit+1
        self.assertEqual(mock_fetch.call_args.kwargs["offset"], 10)
        self.assertEqual(page["has_more"], expected_has_more)
        self.assertEqual(len(page["rows"]), expected_rows)

    def test_interrupt_mid_fetch_delivers_an_interrupted_callback(self):
        # The registry must be live while the fetch waits: an /interrupt arriving mid-fetch
        # has to be known, abort the wait, and turn the callback into `interrupted`.
        payload = {
            "run_id": "r-int-1",
            "code": "select 1",
            "callback_url": "http://backend/cb",
            "callback_token": "cbt",
            "data_plane_url": "http://backend/dp",
            "data_plane_token": "dpt",
        }
        delivered: dict = {}
        interrupt_known: list[bool] = []

        def fetch_then_interrupted(*args, **kwargs):
            interrupt_known.append(kernel_runner.request_interrupt("r-int-1"))
            raise DataPlaneInterrupted("Run interrupted.")

        with (
            patch.object(kernel_runner, "_post_callback", side_effect=lambda url, token, env: delivered.update(env)),
            patch(
                "products.notebooks.backend.sandbox.kernel.data_plane.fetch_query_page",
                side_effect=fetch_then_interrupted,
            ),
        ):
            kernel_runner.execute_run(payload)
        self.assertEqual(interrupt_known, [True])
        self.assertEqual(delivered["status"], "interrupted")
        self.assertEqual(delivered["error"], "Run interrupted.")
        # The run must be unregistered once finished: a later interrupt is unknown.
        self.assertFalse(kernel_runner.request_interrupt("r-int-1"))

    def test_completed_run_stays_ok_when_the_interrupt_races_it(self):
        # An interrupt that lands as the fetch completes must not discard a real result.
        payload = {
            "run_id": "r-int-2",
            "code": "select 1",
            "callback_url": "http://backend/cb",
            "callback_token": "cbt",
            "data_plane_url": "http://backend/dp",
            "data_plane_token": "dpt",
        }
        delivered: dict = {}

        def fetch_and_interrupt(*args, **kwargs):
            kernel_runner.request_interrupt("r-int-2")
            return (["n"], [(1,)], [["n", "Int64"]])

        with (
            patch.object(kernel_runner, "_post_callback", side_effect=lambda url, token, env: delivered.update(env)),
            patch(
                "products.notebooks.backend.sandbox.kernel.data_plane.fetch_query_page",
                side_effect=fetch_and_interrupt,
            ),
        ):
            kernel_runner.execute_run(payload)
        self.assertEqual(delivered["status"], "ok")
        self.assertEqual(delivered["first_page"], [[1]])

    def test_data_plane_poll_aborts_when_the_cancel_event_fires(self):
        # Without the in-loop cancel check, an interrupted HogQL run keeps a thread polling
        # for the full 180s budget and the interrupt does nothing for SQL cells.
        from products.notebooks.backend.sandbox.kernel import data_plane as kernel_data_plane

        class _FakeResponse(io.BytesIO):
            def __init__(self, body: bytes):
                super().__init__(body)
                self.headers = {"Content-Type": "application/json"}

            def __exit__(self, *args):
                return False

        cancel_event = threading.Event()

        def fake_urlopen(request, timeout=None):
            if request.full_url.endswith("/dp"):
                return _FakeResponse(b'{"query_id": "q1"}')
            cancel_event.set()  # the interrupt lands while the query is still running
            return _FakeResponse(b'{"status": "running"}')

        with patch.object(kernel_data_plane.urllib.request, "urlopen", side_effect=fake_urlopen):
            with self.assertRaises(DataPlaneInterrupted):
                kernel_data_plane.fetch_query_page(
                    "http://backend/dp", "t", "select 1", limit=5, cancel_event=cancel_event
                )

    def test_kernel_polls_until_the_arrow_result_arrives(self):
        # The kernel must follow the enqueue → poll protocol: accept the 202 query_id,
        # keep polling through "running" responses, and decode the eventual Arrow 200.
        from products.notebooks.backend.sandbox.kernel import data_plane as kernel_data_plane

        class _FakeResponse(io.BytesIO):
            def __init__(self, content_type: str, body: bytes):
                super().__init__(body)
                self.headers = {"Content-Type": content_type}

            def __exit__(self, *args):
                return False  # keep readable after the with-block, like a drained HTTP response

        arrow_bytes = _rows_to_arrow_bytes(["n"], [(7,)], [["n", "Int64"]])
        responses = iter(
            [
                _FakeResponse("application/json", b'{"query_id": "q1"}'),
                _FakeResponse("application/json", b'{"status": "running"}'),
                _FakeResponse("application/vnd.apache.arrow.stream", arrow_bytes),
            ]
        )
        polled_urls: list[str] = []

        def fake_urlopen(request, timeout=None):
            polled_urls.append(request.full_url)
            return next(responses)

        with (
            patch.object(kernel_data_plane.urllib.request, "urlopen", side_effect=fake_urlopen),
            patch.object(kernel_data_plane.time, "sleep"),
        ):
            columns, rows, _types = kernel_data_plane.fetch_query_page("http://backend/dp", "t", "select 1", limit=5)
        self.assertEqual((columns, rows), (["n"], [(7,)]))
        self.assertEqual(polled_urls[1:], ["http://backend/dp/q1/", "http://backend/dp/q1/"])

    def test_tarball_contains_the_package(self):
        package, version = kernel_package_bytes_and_hash()
        with tarfile.open(fileobj=io.BytesIO(package), mode="r:gz") as tar:
            names = tar.getnames()
        self.assertIn("nb_kernel/server.py", names)
        self.assertIn("nb_kernel/__init__.py", names)
        self.assertEqual(len(version), 16)


class TestSQLV2PythonNodeRun(SimpleTestCase):
    def test_materialize_query_writes_a_readable_arrow_file(self):
        # Journey 4 materialization: the server streams a CH result to a local Arrow *file* the
        # kernel later mmaps. It must be an IPC file (open_file), and the temp must be renamed away.
        import os
        import tempfile

        import pyarrow as pa

        from products.notebooks.backend.sandbox.kernel import data_plane as kernel_data_plane

        arrow_bytes = _rows_to_arrow_bytes(["id", "v"], [(1, 10), (2, 20)], [["id", "Int64"], ["v", "Int64"]])

        class _FakeResponse(io.BytesIO):
            def __init__(self, body: bytes):
                super().__init__(body)
                self.headers = {"Content-Type": "application/vnd.apache.arrow.stream"}

            def __exit__(self, *args):
                return False

        with tempfile.TemporaryDirectory() as directory:
            dest = os.path.join(directory, "df.arrow")
            with patch.object(
                kernel_data_plane.urllib.request,
                "urlopen",
                side_effect=lambda request, timeout=None: _FakeResponse(arrow_bytes),
            ):
                rows = kernel_data_plane.materialize_query_to_file(
                    "http://backend/dp", "t", "select 1", dest, limit=1000
                )
            self.assertEqual(rows, 2)
            table = pa.ipc.open_file(pa.memory_map(dest)).read_all()
            self.assertEqual(table.num_rows, 2)
            self.assertEqual(table.column_names, ["id", "v"])
            self.assertFalse(os.path.exists(dest + ".partial"))

    @parameterized.expand([("python_node", "python"), ("duckdb_node", "duckdb")])
    def test_execute_run_routes_kernel_nodes_to_the_executor(self, _name, node_type):
        result_envelope = {"status": "ok", "columns": ["a"]}
        delivered: dict = {}
        payload = {
            "run_id": f"r-{node_type}",
            "node": {"type": node_type, "code": "1 + 1"},
            "callback_url": "http://backend/cb",
            "callback_token": "t",
        }
        with (
            patch.object(kernel_runner, "_run_kernel_node", return_value=result_envelope) as run_kernel,
            patch.object(kernel_runner, "_post_callback", side_effect=lambda url, token, env: delivered.update(env)),
        ):
            kernel_runner.execute_run(payload)
        run_kernel.assert_called_once()
        self.assertEqual(delivered["status"], "ok")

    def test_result_store_pages_a_stored_frame(self):
        # Kernel-node results page by slicing the on-disk Arrow frame — offsets, bounds and
        # has_more must match what the paging UI expects from the data-plane path.
        import os
        import tempfile

        import pyarrow as pa

        from products.notebooks.backend.sandbox.kernel import result_store

        result_id = "6f8ec2f4-3f42-4b0e-9a2e-5f5b1c9d0a11"
        with tempfile.TemporaryDirectory() as tmp:
            table = pa.table({"id": list(range(10))})
            with pa.OSFile(os.path.join(tmp, f"{result_id}.arrow"), "wb") as sink:
                with pa.ipc.new_file(sink, table.schema) as writer:
                    writer.write_table(table)
            page = result_store.read_page(result_id, offset=4, limit=3, results_dir=tmp)
            self.assertEqual(page["columns"], ["id"])
            self.assertEqual(page["rows"], [[4], [5], [6]])
            self.assertTrue(page["has_more"])
            last = result_store.read_page(result_id, offset=8, limit=5, results_dir=tmp)
            self.assertEqual(last["rows"], [[8], [9]])
            self.assertFalse(last["has_more"])

    @parameterized.expand(
        [
            ("path_traversal_id", "../../etc/passwd"),
            # Valid UUID whose frame was lost with the sandbox disk.
            ("missing_frame", "00000000-0000-0000-0000-000000000000"),
        ]
    )
    def test_result_store_rejects_unusable_result_ids(self, _name, result_id):
        import tempfile

        from products.notebooks.backend.sandbox.kernel import result_store

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(result_store.ResultStoreError):
                result_store.read_page(result_id, offset=0, limit=10, results_dir=tmp)

    def test_execute_run_keeps_hogql_nodes_off_the_kernel(self):
        # A pure-HogQL node must stay on the capped data-plane fetch — never spin up the kernel.
        payload = {
            "run_id": "r-hogql",
            "code": "select 1",
            "callback_url": "http://backend/cb",
            "callback_token": "t",
            "data_plane_url": "u",
            "data_plane_token": "t",
        }
        with (
            patch.object(kernel_runner, "_run_kernel_node") as run_kernel,
            patch.object(kernel_runner, "_post_callback"),
            patch(
                "products.notebooks.backend.sandbox.kernel.data_plane.fetch_query_page",
                return_value=(["n"], [(1,)], [["n", "Int64"]]),
            ),
        ):
            kernel_runner.execute_run(payload)
        run_kernel.assert_not_called()
