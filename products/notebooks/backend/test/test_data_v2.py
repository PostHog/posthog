import json

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.notebooks.backend.data_v2 import (
    kernel_server_secret,
    mint_callback_token,
    mint_command_token,
    verify_command_token,
)
from products.notebooks.backend.models import KernelRuntime, Notebook, NotebookNodeRun


class TestDataV2Callback(APIBaseTest):
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


class TestDataV2Run(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, short_id="nbrun01")
        self.url = f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/data_v2/run/"

    def _create_runtime(self, server_url=None):
        return KernelRuntime.objects.create(
            team=self.team,
            notebook=self.notebook,
            notebook_short_id=self.notebook.short_id,
            user=self.user,
            status=KernelRuntime.Status.RUNNING,
            backend=KernelRuntime.Backend.DOCKER,
            sandbox_id="sbx-1",
            server_url=server_url,
        )

    @patch("products.notebooks.backend.presentation.views.notebook.is_data_v2_enabled", return_value=True)
    def test_run_without_kernel_returns_409(self, _mock_enabled):
        response = self.client.post(self.url, data={"node_id": "n1", "code": "select 1"}, format="json")
        self.assertEqual(response.status_code, 409)
        run = NotebookNodeRun.objects.for_team(self.team.id).filter(notebook=self.notebook).first()
        assert run is not None
        self.assertEqual(run.status, NotebookNodeRun.Status.FAILED)

    @patch("products.notebooks.backend.data_v2.requests.post")
    @patch("products.notebooks.backend.presentation.views.notebook.is_data_v2_enabled", return_value=True)
    def test_run_dispatches_to_ready_server(self, _mock_enabled, mock_post):
        self._create_runtime(server_url="http://localhost:12345")

        response = self.client.post(self.url, data={"node_id": "n1", "code": "select 1"}, format="json")

        self.assertEqual(response.status_code, 200)
        run_id = response.json()["run_id"]
        self.assertEqual(
            NotebookNodeRun.objects.for_team(self.team.id).get(id=run_id).status,
            NotebookNodeRun.Status.RUNNING,
        )
        mock_post.assert_called_once()
        self.assertIn("/run", mock_post.call_args.args[0])
        self.assertEqual(mock_post.call_args.kwargs["json"]["run_id"], run_id)
        self.assertTrue(mock_post.call_args.kwargs["headers"]["Authorization"].startswith("Bearer "))

    @patch("products.notebooks.backend.data_v2.requests.post")
    @patch("products.notebooks.backend.data_v2.requests.get")
    @patch("products.notebooks.backend.data_v2.get_sandbox_class_for_backend")
    @patch("products.notebooks.backend.presentation.views.notebook.is_data_v2_enabled", return_value=True)
    def test_run_bootstraps_server_when_absent(self, _mock_enabled, mock_get_sandbox_class, mock_get, mock_post):
        self._create_runtime(server_url=None)
        fake_sandbox = MagicMock()
        fake_sandbox.get_connect_credentials.return_value = MagicMock(url="http://localhost:12345", token=None)
        mock_get_sandbox_class.return_value.get_by_id.return_value = fake_sandbox
        mock_get.return_value.status_code = 200

        response = self.client.post(self.url, data={"node_id": "n1", "code": "x"}, format="json")

        self.assertEqual(response.status_code, 200)
        # Two writes at bootstrap: the command-auth secret and the server script.
        self.assertEqual(fake_sandbox.write_file.call_count, 2)
        fake_sandbox.execute.assert_called_once()
        self.assertEqual(KernelRuntime.objects.get(sandbox_id="sbx-1").server_url, "http://localhost:12345")
        mock_post.assert_called_once()


class TestDataV2CommandToken(SimpleTestCase):
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
