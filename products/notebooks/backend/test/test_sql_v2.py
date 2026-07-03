import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.notebooks.backend.models import KernelRuntime, Notebook, NotebookNodeRun
from products.notebooks.backend.sql_v2 import (
    kernel_server_secret,
    mint_callback_token,
    mint_command_token,
    verify_command_token,
)
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
            self.run = NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                node_id="node-1",
                status=NotebookNodeRun.Status.RUNNING,
            )
        self.url = f"/internal/notebooks/runs/{self.run.id}/result/"
        self.envelope = {
            "status": "ok",
            "columns": ["count"],
            "row_count": 1,
            "first_page": [[42]],
            "result_id": str(self.run.id),
        }

    def _post(self, token: str, envelope=None):
        return self.client.post(
            self.url,
            data=json.dumps({"envelope": envelope if envelope is not None else self.envelope}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def _reload_run(self) -> NotebookNodeRun:
        return NotebookNodeRun.objects.for_team(self.team.id).get(id=self.run.id)

    def test_valid_token_stores_result(self):
        token = mint_callback_token(str(self.run.id), self.team.id)
        response = self._post(token)
        self.assertEqual(response.status_code, 200)
        run = self._reload_run()
        self.assertEqual(run.status, NotebookNodeRun.Status.DONE)
        self.assertEqual(run.envelope["first_page"], [[42]])
        self.assertEqual(str(run.result_id), str(self.run.id))

    def test_redelivery_is_idempotent(self):
        token = mint_callback_token(str(self.run.id), self.team.id)
        self._post(token)
        self._post(token)
        count = NotebookNodeRun.objects.for_team(self.team.id).filter(id=self.run.id).count()
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

    @patch("products.notebooks.backend.sql_v2.requests.post")
    def test_dispatch_activity_posts_to_ready_server(self, mock_post):
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
        self.assertEqual(self._reload(run).status, NotebookNodeRun.Status.RUNNING)

    def test_mark_failed_activity(self):
        run = self._create_run()
        mark_sql_v2_run_failed_activity(self._run_input(run))
        self.assertEqual(self._reload(run).status, NotebookNodeRun.Status.FAILED)


class TestSQLV2CommandToken(SimpleTestCase):
    def test_valid_token_verifies(self):
        secret = kernel_server_secret("rt-1")
        self.assertTrue(verify_command_token(secret, "run-1", mint_command_token(secret, "run-1")))

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
        self.assertFalse(verify_command_token(verify_secret, run_id, token))
