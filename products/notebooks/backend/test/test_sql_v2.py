import io
import json
import math
import tarfile
import datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core import signing
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.notebooks.backend.kernel_package import kernel_package_bytes_and_hash
from products.notebooks.backend.models import KernelRuntime, Notebook, NotebookNodeRun
from products.notebooks.backend.sandbox.kernel import (
    auth as kernel_auth,
    envelope as kernel_envelope,
    runner as kernel_runner,
)
from products.notebooks.backend.sandbox.kernel.data_plane import DataPlaneError, decode_arrow_stream
from products.notebooks.backend.sql_v2 import (
    kernel_server_secret,
    mint_callback_token,
    mint_command_token,
    mint_data_plane_token,
    verify_data_plane_token,
)
from products.notebooks.backend.sql_v2_data_plane import _rows_to_arrow_bytes
from products.notebooks.backend.temporal.sql_v2 import (
    SQLV2RunInput,
    dispatch_sql_v2_run_activity,
    mark_sql_v2_run_failed_activity,
)


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
        mock_start.assert_called_once()
        self.assertEqual(str(mock_start.call_args.args[0].run_id), run_id)

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_blank_code_is_rejected_before_dispatch(self, _mock_enabled, mock_start):
        # A stale-attribute FE bug once sent empty code all the way into the sandbox; fail fast here instead.
        response = self.client.post(self.run_url, data={"node_id": "n1", "code": ""}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(NotebookNodeRun.objects.for_team(self.team.id).filter(notebook=self.notebook).count(), 0)
        mock_start.assert_not_called()

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
        ]
    )
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_result_shape_by_status(self, status, envelope, error, expected_result, expected_error, _mock_enabled):
        run = self._create_run(status, envelope=envelope, error=error)
        response = self.client.get(self._url(str(run.id)))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], status)
        # result is only surfaced when done; error only when failed
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
        KernelRuntime.objects.create(
            team=self.team,
            notebook=self.notebook,
            notebook_short_id=self.notebook.short_id,
            user=self.user,
            status=KernelRuntime.Status.RUNNING,
            backend=KernelRuntime.Backend.DOCKER,
            sandbox_id="sbx-1",
            server_url="http://localhost:12345",
        )
        dispatch_sql_v2_run_activity(self._run_input(run))
        mock_post.assert_called_once()
        self.assertIn("/run", mock_post.call_args.args[0])
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["code"], "select 1")
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
        kwargs = {"data": json.dumps(body), "content_type": "application/json"}
        if token is not None:
            kwargs["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return self.client.post(self.URL, **kwargs)

    def _token(self, short_id: str | None = None) -> str:
        return mint_data_plane_token(short_id or self.notebook.short_id, self.team.id, self.user.id)

    def test_runs_query_and_returns_arrow(self):
        response = self._post({"query": "select 1 as answer"}, token=self._token())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Content-Type"], "application/vnd.apache.arrow.stream")
        columns, rows, types = decode_arrow_stream(response.content)
        self.assertEqual(columns, ["answer"])
        self.assertEqual(rows, [(1,)])
        # The real ClickHouse type must survive the Arrow round-trip (schema metadata).
        self.assertEqual(types[0][0], "answer")
        self.assertIn("Int", types[0][1])

    def test_outer_limit_and_offset_cap_the_page(self):
        response = self._post({"query": "select number from numbers(10)", "limit": 3, "offset": 2}, token=self._token())
        self.assertEqual(response.status_code, 200, response.content)
        _columns, rows, _types = decode_arrow_stream(response.content)
        self.assertEqual(rows, [(2,), (3,), (4,)])

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

    def test_tarball_contains_the_package(self):
        package, version = kernel_package_bytes_and_hash()
        with tarfile.open(fileobj=io.BytesIO(package), mode="r:gz") as tar:
            names = tar.getnames()
        self.assertIn("nb_kernel/server.py", names)
        self.assertIn("nb_kernel/__init__.py", names)
        self.assertEqual(len(version), 16)
