import json
from typing import Any

from unittest.mock import patch

from django.test import TestCase, override_settings

from parameterized import parameterized

from posthog.models import Organization, Team

from products.tasks.backend.logic.services.connection_token import (
    create_sandbox_event_ingest_token,
    reset_sandbox_jwt_key_cache,
)
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.tests.test_api import TEST_RSA_PRIVATE_KEY


@override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
class TestAgentProxyCallback(TestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_sandbox_jwt_key_cache()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.task_run: TaskRun = self.task.create_run()

    def tearDown(self) -> None:
        reset_sandbox_jwt_key_cache()
        super().tearDown()

    def _url(self, run_id: str | None = None) -> str:
        return f"/internal/tasks/runs/{run_id or self.task_run.id}/agent-proxy-callback/"

    def _token(self, run: TaskRun | None = None) -> str:
        return create_sandbox_event_ingest_token(run or self.task_run)

    def _body(self, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "kind": "heartbeat",
            "agent_active": True,
            "task_id": str(self.task.id),
            "team_id": self.team.id,
        }
        body.update(overrides)
        return body

    def _post(self, body: dict[str, Any], token: str | None, run_id: str | None = None, secret: str | None = None):
        kwargs: dict[str, Any] = {"content_type": "application/json"}
        if token is not None:
            kwargs["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        if secret is not None:
            kwargs["HTTP_X_AGENT_PROXY_SECRET"] = secret
        return self.client.post(self._url(run_id), data=json.dumps(body), **kwargs)

    def test_get_method_returns_405(self) -> None:
        response = self.client.get(self._url(), HTTP_AUTHORIZATION=f"Bearer {self._token()}")
        self.assertEqual(response.status_code, 405)

    @override_settings(AGENT_PROXY_CALLBACK_SECRET="proxy-only-secret")
    def test_callback_secret_required_when_configured(self) -> None:
        # A valid ingest JWT without the shared secret is rejected: the JWT is also held by the
        # sandbox, so the secret is what proves the call came from the agent-proxy.
        self.assertEqual(self._post(self._body(), token=self._token()).status_code, 403)
        self.assertEqual(self._post(self._body(), token=self._token(), secret="wrong").status_code, 403)
        # Correct secret passes the gate and reaches body handling (empty body is a 400, not a 403).
        self.assertEqual(self._post({}, token=self._token(), secret="proxy-only-secret").status_code, 400)

    @override_settings(AGENT_PROXY_CALLBACK_SECRET=None, DEBUG=False, TEST=False)
    def test_callback_fails_closed_when_secret_unset_outside_dev(self) -> None:
        # Production with no secret provisioned: the endpoint refuses even a valid ingest JWT
        # rather than letting sandboxes drive side effects directly.
        response = self._post(self._body(), token=self._token())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Agent-proxy callback secret is not configured")

    @override_settings(AGENT_PROXY_CALLBACK_SECRET=None)
    def test_callback_allows_unset_secret_in_test_mode(self) -> None:
        # Local dev/test has no proxy deployment to share a secret with; the gate stays open so
        # the callback remains exercisable (empty body reaches handling: 400, not 403).
        self.assertEqual(self._post({}, token=self._token()).status_code, 400)

    def test_missing_authorization_returns_401(self) -> None:
        response = self.client.post(self._url(), data=json.dumps(self._body()), content_type="application/json")
        self.assertEqual(response.status_code, 401)

    @parameterized.expand(
        [
            ("no_bearer_prefix", "Token abc"),
            ("empty_bearer", "Bearer "),
            ("garbage_token", "Bearer not-a-jwt"),
        ]
    )
    def test_invalid_authorization_returns_401(self, _name: str, header: str) -> None:
        response = self.client.post(
            self._url(),
            data=json.dumps(self._body()),
            content_type="application/json",
            HTTP_AUTHORIZATION=header,
        )
        self.assertEqual(response.status_code, 401)

    def test_token_run_mismatch_returns_403(self) -> None:
        other_run = self.task.create_run()
        response = self._post(self._body(), token=self._token(other_run))
        self.assertEqual(response.status_code, 403)

    def test_body_task_id_mismatch_returns_403(self) -> None:
        response = self._post(self._body(task_id="00000000-0000-0000-0000-000000000000"), token=self._token())
        self.assertEqual(response.status_code, 403)

    def test_body_team_id_mismatch_returns_403(self) -> None:
        response = self._post(self._body(team_id=self.team.id + 999), token=self._token())
        self.assertEqual(response.status_code, 403)

    def test_invalid_body_returns_400(self) -> None:
        response = self._post({"kind": "heartbeat"}, token=self._token())
        self.assertEqual(response.status_code, 400)

    def test_heartbeat_dispatches_when_active(self) -> None:
        with patch.object(TaskRun, "heartbeat_workflow") as heartbeat:
            response = self._post(self._body(kind="heartbeat", agent_active=True), token=self._token())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["dispatched"])
        heartbeat.assert_called_once_with(agent_active=True)

    def test_heartbeat_not_dispatched_when_inactive(self) -> None:
        with patch.object(TaskRun, "heartbeat_workflow") as heartbeat:
            response = self._post(self._body(kind="heartbeat", agent_active=False), token=self._token())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["dispatched"])
        heartbeat.assert_not_called()

    def test_awaiting_input_dispatches_for_interactive_run(self) -> None:
        run = self.task.create_run(mode="interactive")
        with patch("products.tasks.backend.agent_proxy_callback.notify_task_run_awaiting_input") as notify:
            response = self._post(
                self._body(kind="awaiting_input", agent_active=False),
                token=self._token(run),
                run_id=str(run.id),
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["dispatched"])
        notify.assert_called_once()

    def test_awaiting_input_skipped_for_background_run(self) -> None:
        with patch("products.tasks.backend.agent_proxy_callback.notify_task_run_awaiting_input") as notify:
            response = self._post(self._body(kind="awaiting_input", agent_active=False), token=self._token())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["dispatched"])
        notify.assert_not_called()

    def test_unknown_run_returns_200_not_dispatched(self) -> None:
        run = self.task.create_run()
        run_id = str(run.id)
        token = self._token(run)
        TaskRun.objects.filter(id=run_id).delete()
        with patch.object(TaskRun, "heartbeat_workflow") as heartbeat:
            response = self._post(self._body(kind="heartbeat", agent_active=True), token=token, run_id=run_id)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["dispatched"])
        heartbeat.assert_not_called()
