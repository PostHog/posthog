from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration import Integration

from products.slack_app.backend.facade.enums import SlackReactionKind
from products.slack_app.backend.facade.types import SlackReactionChoice, SlackResolvedReaction
from products.slack_app.backend.models import SlackSettings
from products.slack_app.backend.services.reaction_settings import parse_reactions, resolve_reactions
from products.slack_app.backend.temporal.activities.messaging import mark_slack_app_message_processing_activity
from products.slack_app.backend.temporal.types import SlackAppMessageReactionInput

WORKING = SlackReactionKind.WORKING
DONE = SlackReactionKind.DONE


class TestReactionSettings(SimpleTestCase):
    def test_nothing_stored_keeps_todays_behavior(self) -> None:
        assert resolve_reactions({}, {}) == {
            SlackReactionKind.WORKING: SlackResolvedReaction(emoji="eyes", enabled=True),
            SlackReactionKind.DONE: SlackResolvedReaction(emoji="white_check_mark", enabled=False),
            SlackReactionKind.ERROR: SlackResolvedReaction(emoji="x", enabled=True),
            SlackReactionKind.POLITE: SlackResolvedReaction(emoji="orange_heart", enabled=True),
        }

    @parameterized.expand(
        [
            ("personal_wins", {WORKING: "hog-ws"}, {WORKING: "hog-me"}, "hog-me"),
            ("workspace_when_no_personal", {WORKING: "hog-ws"}, {}, "hog-ws"),
            ("personal_without_workspace", {}, {WORKING: "hog-me"}, "hog-me"),
        ]
    )
    def test_emoji_fallback(self, _name: str, workspace: dict, personal: dict, expected: str) -> None:
        resolved = resolve_reactions(
            {kind: SlackReactionChoice(emoji=emoji) for kind, emoji in workspace.items()},
            {kind: SlackReactionChoice(emoji=emoji) for kind, emoji in personal.items()},
        )

        assert resolved[WORKING].emoji == expected

    def test_fields_fall_back_separately(self) -> None:
        resolved = resolve_reactions(
            {DONE: SlackReactionChoice(emoji="hog-done", enabled=True)},
            {DONE: SlackReactionChoice(enabled=False)},
        )

        assert resolved[DONE] == SlackResolvedReaction(emoji="hog-done", enabled=False)

    def test_parse_drops_what_slack_would_refuse(self) -> None:
        parsed = parse_reactions(
            {
                "working": {"emoji": "Not An Emoji!", "enabled": "yes"},
                "done": {"emoji": "tada", "enabled": True},
                "polite": {"emoji": "thumbsup::skin-tone-3"},
                "unknown_kind": {"emoji": "tada"},
                "error": "warning",
            }
        )

        assert parsed == {
            SlackReactionKind.WORKING: SlackReactionChoice(emoji=None, enabled=None),
            SlackReactionKind.DONE: SlackReactionChoice(emoji="tada", enabled=True),
            SlackReactionKind.POLITE: SlackReactionChoice(emoji="thumbsup::skin-tone-3", enabled=None),
        }


class TestReactionWhenTheBotStartsWork(BaseTest):
    @parameterized.expand(
        [
            ("nothing_stored", True, None, None, "eyes"),
            ("workspace_choice", True, {"working": {"emoji": "hog-ws"}}, None, "hog-ws"),
            (
                "personal_over_workspace",
                True,
                {"working": {"emoji": "hog-ws"}},
                {"working": {"emoji": "hog-me"}},
                "hog-me",
            ),
            ("personal_off", True, {"working": {"emoji": "hog-ws"}}, {"working": {"enabled": False}}, None),
            ("workspace_off", True, {"working": {"enabled": False}}, None, None),
            (
                "flag_off_keeps_the_default",
                False,
                {"working": {"emoji": "hog-ws"}},
                {"working": {"enabled": False}},
                "eyes",
            ),
        ]
    )
    def test_queue_swaps_the_hourglass_for_the_resolved_working_reaction(
        self, _name: str, flag_on: bool, workspace: dict | None, personal: dict | None, expected: str | None
    ) -> None:
        cache.clear()
        integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T01", config={}, sensitive_config={"access_token": "xoxb"}
        )
        if workspace is not None:
            SlackSettings.objects.create(slack_workspace_id="T01", slack_user_id=None, reactions=workspace)
        if personal is not None:
            SlackSettings.objects.create(slack_workspace_id="T01", slack_user_id="U01", reactions=personal)
        client = MagicMock()

        with (
            patch("posthoganalytics.feature_enabled", return_value=flag_on),
            patch("products.slack_app.backend.temporal.activities.messaging.SlackIntegration") as slack,
        ):
            slack.return_value.client = client
            mark_slack_app_message_processing_activity(
                SlackAppMessageReactionInput(
                    integration_id=integration.id,
                    slack_team_id="T01",
                    channel="C01",
                    message_ts="1.1",
                    slack_user_id="U01",
                )
            )

        client.reactions_remove.assert_called_once_with(channel="C01", timestamp="1.1", name="hourglass")
        added = [call.kwargs["name"] for call in client.reactions_add.call_args_list]
        assert added == ([expected] if expected else [])
