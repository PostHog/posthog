import json

from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.helpers.slack_subscription_explore import (
    EXPLORE_ACTION_ID,
    EXPLORE_VIEW_CALLBACK_ID,
    REQUIRED_SLACK_SCOPES,
    SUBSCRIPTION_EXPLORE_BUTTON_FEATURE_FLAG_KEY,
    bot_is_ready,
    decode_explore_token,
    explore_button_enabled,
    make_explore_token,
)
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.slack_app.backend.api import (
    _build_explore_modal,
    _escape_slack_text,
    _explore_token_from_payload,
    _extract_explore_hints,
)


class TestSubscriptionExploreToken(TestCase):
    def test_token_round_trips(self) -> None:
        token = make_explore_token(integration_id=42, resource_name="Weekly report")
        decoded = decode_explore_token(token)
        assert decoded == {"integration_id": 42, "resource_name": "Weekly report"}

    def test_decode_rejects_garbage(self) -> None:
        assert decode_explore_token("not-a-real-token") is None
        assert decode_explore_token("") is None


class TestBotIsReady(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=self.org, name="Team")

    def _integration(self, scopes: frozenset[str]) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T1",
            config={"scope": ",".join(sorted(scopes))},
            sensitive_config={"access_token": "xoxb-test"},
        )

    @parameterized.expand(
        [
            ("full_scopes", REQUIRED_SLACK_SCOPES, True),
            ("missing_scopes", frozenset({"chat:write"}), False),
        ]
    )
    def test_bot_is_ready(self, _name: str, scopes: frozenset[str], expected: bool) -> None:
        assert bot_is_ready(self._integration(scopes)) is expected


def _button_click_payload(token: str) -> dict:
    return {"type": "block_actions", "actions": [{"action_id": EXPLORE_ACTION_ID, "value": token}]}


def _view_submission_payload(token: str) -> dict:
    return {"type": "view_submission", "view": {"private_metadata": json.dumps({"token": token, "channel": "C1"})}}


class TestExploreHints(TestCase):
    @parameterized.expand(
        [
            ("button_click", 7, _button_click_payload),
            ("view_submission", 9, _view_submission_payload),
        ]
    )
    def test_token_extracted(self, _name: str, integration_id: int, build_payload) -> None:
        token = make_explore_token(integration_id=integration_id, resource_name="r")
        payload = build_payload(token)
        assert _explore_token_from_payload(payload) == token
        assert _extract_explore_hints(payload) == integration_id

    def test_unrelated_payload_yields_no_hint(self) -> None:
        payload = {"type": "block_actions", "actions": [{"action_id": "posthog_code_repo_select", "value": "x"}]}
        assert _explore_token_from_payload(payload) == ""
        assert _extract_explore_hints(payload) is None

    def test_view_submission_with_null_view_does_not_raise(self) -> None:
        # The token extractors run on every interactivity payload, so a null `view` must not raise here.
        # (The submit handler's own null-view tolerance is covered in TestSubscriptionExploreInteractivity.)
        assert _explore_token_from_payload({"type": "view_submission", "view": None}) == ""
        assert _extract_explore_hints({"type": "view_submission", "view": None}) is None


class TestEscapeSlackText(TestCase):
    def test_escapes_reserved_chars_so_mentions_do_not_expand(self) -> None:
        assert _escape_slack_text("ping <!channel> & <@U123>") == "ping &lt;!channel&gt; &amp; &lt;@U123&gt;"

    def test_plain_text_unchanged(self) -> None:
        assert _escape_slack_text("what drove the spike?") == "what drove the spike?"


class TestBuildExploreModal(TestCase):
    def test_modal_shape(self) -> None:
        modal = _build_explore_modal(private_metadata='{"token": "t"}', resource_name="Signups")
        assert modal["type"] == "modal"
        assert modal["callback_id"] == EXPLORE_VIEW_CALLBACK_ID
        assert modal["private_metadata"] == '{"token": "t"}'
        # The resource name is surfaced in the heading, and there's a free-text input to fill.
        assert "Signups" in modal["blocks"][0]["text"]["text"]
        assert any(block.get("type") == "input" for block in modal["blocks"])


class TestExploreButtonEnabled(TestCase):
    def test_empty_organization_id_is_fail_closed(self) -> None:
        # No flag call when we can't resolve the org — disabled.
        with patch("posthog.helpers.slack_subscription_explore.posthoganalytics.feature_enabled") as mock_flag:
            assert explore_button_enabled(organization_id="") is False
            mock_flag.assert_not_called()

    @patch("posthog.helpers.slack_subscription_explore.posthoganalytics.feature_enabled")
    def test_evaluates_org_flag(self, mock_flag) -> None:
        mock_flag.return_value = True
        assert explore_button_enabled(organization_id="org-123") is True
        mock_flag.assert_called_once()
        args, kwargs = mock_flag.call_args
        assert args[0] == SUBSCRIPTION_EXPLORE_BUTTON_FEATURE_FLAG_KEY
        assert args[1] == "org-123"
        assert kwargs["groups"] == {"organization": "org-123"}

    @patch("posthog.helpers.slack_subscription_explore.posthoganalytics.feature_enabled", return_value=None)
    def test_unknown_flag_is_false(self, _mock_flag) -> None:
        assert explore_button_enabled(organization_id="org-123") is False
