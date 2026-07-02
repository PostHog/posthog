from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration

from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run
from products.skills.backend.models.skills import LLMSkill

WEBCLIENT_PATH = "posthog.models.integration.WebClient"
NOTIFY_TOOLS = ["emit_report", "edit_report", "send_slack_message"]


class TestScoutNotifyAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.skill = LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-general",
            description="delivery-opted scout",
            body="# scout",
            allowed_tools=NOTIFY_TOOLS,
        )
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T1",
            config={"scope": "chat:write"},
            sensitive_config={"access_token": "xoxb-test"},
        )
        _authenticate_as_scout(self)

    def _url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/notify/"

    def _run_with_delivery(self, **run_overrides):
        run = _make_run(self.team, **run_overrides)
        run.scout_config.delivery_config = {
            "slack": {
                "integration_id": self.integration.id,
                "channel_id": "C_CONFIGURED",
                "channel_name": "account-pulse",
            }
        }
        run.scout_config.save(update_fields=["delivery_config"])
        return run

    def _payload(self, **overrides) -> dict:
        body: dict = {"text": "Usage down 60% over two weeks.", "account_name": "Initech"}
        body.update(overrides)
        return body

    def _client_mock(self, webclient_cls) -> MagicMock:
        client = webclient_cls.return_value
        client.chat_postMessage.return_value = {"ok": True, "ts": "123.45"}
        client.users_lookupByEmail.return_value = {"user": {"id": "U_OWNER"}}
        return client

    @patch(WEBCLIENT_PATH)
    def test_successive_notifications_accumulate_in_the_audit(self, webclient_cls) -> None:
        self._client_mock(webclient_cls)
        run = self._run_with_delivery()
        self.client.post(self._url(str(run.id)), self._payload(account_name="Acme"), format="json")
        self.client.post(self._url(str(run.id)), self._payload(account_name="Initech"), format="json")
        run.refresh_from_db()
        assert [entry["account_name"] for entry in run.notifications] == ["Acme", "Initech"]

    @patch(WEBCLIENT_PATH)
    def test_notify_posts_only_to_configured_channel(self, webclient_cls) -> None:
        client = self._client_mock(webclient_cls)
        run = self._run_with_delivery()
        response = self.client.post(self._url(str(run.id)), self._payload(channel="C_EVIL"), format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert client.chat_postMessage.call_args.kwargs["channel"] == "C_CONFIGURED"
        assert response.json()["channel"] == "#account-pulse"

    @patch(WEBCLIENT_PATH)
    def test_notify_tags_owner_and_links_report(self, webclient_cls) -> None:
        client = self._client_mock(webclient_cls)
        run = self._run_with_delivery()
        report_id = "0198c07e-0000-0000-0000-000000000001"
        run.emitted_report_ids = [report_id]
        run.save(update_fields=["emitted_report_ids"])
        response = self.client.post(
            self._url(str(run.id)),
            self._payload(owner_email="owner@example.com", report_id=report_id),
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["owner_tagged"] is True
        blocks = client.chat_postMessage.call_args.kwargs["blocks"]
        assert any("<@U_OWNER>" in str(block) for block in blocks)
        assert any(report_id in str(block) for block in blocks)
        run.refresh_from_db()
        assert len(run.notifications) == 1
        assert run.notifications[0]["owner_tagged"] is True
        assert run.notifications[0]["report_id"] == report_id

    @patch(WEBCLIENT_PATH)
    def test_notify_owner_lookup_miss_falls_back_to_label(self, webclient_cls) -> None:
        client = self._client_mock(webclient_cls)
        client.users_lookupByEmail.side_effect = SlackApiError("users_not_found", {"error": "users_not_found"})
        run = self._run_with_delivery()
        response = self.client.post(
            self._url(str(run.id)),
            self._payload(owner_email="owner@example.com", owner_label="Jane Doe (Salesforce)"),
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["owner_tagged"] is False
        blocks = client.chat_postMessage.call_args.kwargs["blocks"]
        assert any("Jane Doe (Salesforce)" in str(block) for block in blocks)

    @patch(WEBCLIENT_PATH)
    def test_notify_requires_skill_opt_in(self, webclient_cls) -> None:
        self._client_mock(webclient_cls)
        self.skill.allowed_tools = ["emit_report", "edit_report"]
        self.skill.save(update_fields=["allowed_tools"])
        run = self._run_with_delivery()
        response = self.client.post(self._url(str(run.id)), self._payload(), format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(
        [
            ("absent_config", None),
            ("missing_integration_id", {"slack": {"channel_id": "C_CONFIGURED", "channel_name": "x"}}),
        ]
    )
    @patch(WEBCLIENT_PATH)
    def test_notify_rejects_missing_delivery_config(self, _name, delivery, webclient_cls) -> None:
        self._client_mock(webclient_cls)
        run = _make_run(self.team)
        run.scout_config.delivery_config = delivery
        run.scout_config.save(update_fields=["delivery_config"])
        response = self.client.post(self._url(str(run.id)), self._payload(), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "no_delivery_config"

    @patch(WEBCLIENT_PATH)
    def test_notify_enforces_per_run_cap(self, webclient_cls) -> None:
        client = self._client_mock(webclient_cls)
        run = self._run_with_delivery()
        run.notifications = [{"channel_id": "C_CONFIGURED", "ts": str(i)} for i in range(5)]
        run.save(update_fields=["notifications"])
        response = self.client.post(self._url(str(run.id)), self._payload(), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "notification_cap_reached"
        client.chat_postMessage.assert_not_called()

    @patch(WEBCLIENT_PATH)
    def test_notify_rejects_report_id_not_from_this_run(self, webclient_cls) -> None:
        client = self._client_mock(webclient_cls)
        run = self._run_with_delivery()
        response = self.client.post(
            self._url(str(run.id)),
            self._payload(report_id="0198c07e-0000-0000-0000-00000000dead"),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "unknown_report_id"
        client.chat_postMessage.assert_not_called()

    @patch(WEBCLIENT_PATH)
    def test_notify_maps_slack_rejection_to_channel_unavailable(self, webclient_cls) -> None:
        client = self._client_mock(webclient_cls)
        client.chat_postMessage.side_effect = SlackApiError("not_in_channel", {"error": "not_in_channel"})
        run = self._run_with_delivery()
        response = self.client.post(self._url(str(run.id)), self._payload(), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "channel_unavailable"
        run.refresh_from_db()
        assert (run.notifications or []) == []
