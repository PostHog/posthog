import json
from typing import Any

from unittest.mock import patch

from django.test import TestCase, override_settings

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.api.oauth.provisioning_review_slack import BLOCK_ACTION_ID, BLOCK_ID_PREFIX

from products.slack_app.backend.tests.helpers import sign_slack_request

SIGNING_SECRET = "posthog-code-test-secret"


@override_settings(DEBUG=True)
@patch("products.slack_app.backend.api.SlackIntegration")
class TestProvisioningReviewInteractivity(TestCase):
    # DEBUG keeps the endpoint local-only, so a click for another region is dropped here instead of proxied.

    def _post(self, payload: dict[str, Any]) -> Any:
        body = f"payload={json.dumps(payload)}"
        signed = sign_slack_request(body.encode(), SIGNING_SECRET)
        return APIClient().post(
            "/slack/interactivity-callback/",
            data=body,
            content_type="application/x-www-form-urlencoded",
            headers={"x-slack-signature": signed.signature, "x-slack-request-timestamp": signed.timestamp},
        )

    @parameterized.expand([("this_region", "", True), ("other_region", "EU", False)])
    def test_block_click_is_handled_only_in_the_review_region(self, mock_slack_cls, _name, region, handled) -> None:
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": SIGNING_SECRET}
        payload = {
            "type": "block_actions",
            "team": {"id": "T_POSTHOG"},
            "user": {"id": "U123"},
            "trigger_id": "trigger",
            "actions": [{"action_id": BLOCK_ACTION_ID, "block_id": f"{BLOCK_ID_PREFIX}:{region}:review-id"}],
        }

        with patch("posthog.api.oauth.provisioning_review_slack.handle_block_click") as handle_block_click:
            response = self._post(payload)

        assert response.status_code == 200
        assert handle_block_click.called is handled
