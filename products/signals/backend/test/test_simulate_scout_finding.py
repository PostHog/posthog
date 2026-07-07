"""Tests for the `simulate_scout_finding` management command.

The compose+send core (`send_scout_slack_notification`) is covered end-to-end via
the notify endpoint in `test_scout_notify_api.py`; here we lock the command
surface — provisioning preconditions, the simulation label, and the run=None path
leaving no run state behind.
"""

from __future__ import annotations

from io import StringIO

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun

WEBCLIENT_PATH = "posthog.models.integration.WebClient"
SKILL_NAME = "signals-scout-slack-csm-account-pulse"


# The command posts a live message; Django tests run DEBUG=False, so it simulates local use under DEBUG.
@override_settings(DEBUG=True)
class TestSimulateScoutFindingCommand(BaseTest):
    def _config_with_delivery(self) -> SignalScoutConfig:
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T1",
            config={"scope": "chat:write"},
            sensitive_config={"access_token": "xoxb-test"},
        )
        return SignalScoutConfig.objects.create(
            team=self.team,
            skill_name=SKILL_NAME,
            delivery_config={
                "slack": {
                    "integration_id": integration.id,
                    "channel_id": "C_CONFIGURED",
                    "channel_name": "account-pulse",
                }
            },
        )

    def _client_mock(self, webclient_cls: MagicMock) -> MagicMock:
        client = webclient_cls.return_value
        client.chat_postMessage.return_value = {"ok": True, "ts": "123.45"}
        return client

    @parameterized.expand(
        [
            ("no_config", False, "provision_persona_scouts"),
            ("config_without_delivery", True, "no Slack delivery channel"),
        ]
    )
    def test_errors_clearly_when_delivery_is_not_provisioned(self, _name, create_config, match) -> None:
        if create_config:
            SignalScoutConfig.objects.create(team=self.team, skill_name=SKILL_NAME, delivery_config=None)
        with pytest.raises(CommandError, match=match):
            call_command("simulate_scout_finding", "--team-id", str(self.team.id))

    @patch(WEBCLIENT_PATH)
    def test_posts_labeled_simulated_finding_without_run_rows(self, webclient_cls) -> None:
        client = self._client_mock(webclient_cls)
        self._config_with_delivery()
        out = StringIO()
        call_command("simulate_scout_finding", "--team-id", str(self.team.id), stdout=out)
        assert client.chat_postMessage.call_args.kwargs["channel"] == "C_CONFIGURED"
        blocks = client.chat_postMessage.call_args.kwargs["blocks"]
        assert any("Simulated finding" in str(block) for block in blocks)
        assert SignalScoutRun.objects.for_team(self.team.id).count() == 0
        output = out.getvalue()
        assert "#account-pulse" in output
        assert "123.45" in output

    @patch(WEBCLIENT_PATH)
    def test_maps_slack_rejection_to_command_error(self, webclient_cls) -> None:
        client = self._client_mock(webclient_cls)
        client.chat_postMessage.side_effect = SlackApiError("not_in_channel", {"error": "not_in_channel"})
        self._config_with_delivery()
        with pytest.raises(CommandError, match="channel_unavailable"):
            call_command("simulate_scout_finding", "--team-id", str(self.team.id))

    @parameterized.expand(
        [
            ("without_force_blocks", False, True),
            ("with_force_proceeds", True, False),
        ]
    )
    @override_settings(DEBUG=False)
    @patch(WEBCLIENT_PATH)
    def test_refuses_live_send_outside_debug_unless_forced(self, _name, force, expect_error, webclient_cls) -> None:
        client = self._client_mock(webclient_cls)
        self._config_with_delivery()
        args = ["simulate_scout_finding", "--team-id", str(self.team.id)]
        if force:
            args.append("--force")
        if expect_error:
            with pytest.raises(CommandError, match="--force"):
                call_command(*args)
            client.chat_postMessage.assert_not_called()
        else:
            call_command(*args)
            client.chat_postMessage.assert_called_once()
