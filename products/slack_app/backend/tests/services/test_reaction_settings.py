from django.test import SimpleTestCase

from parameterized import parameterized

from products.slack_app.backend.facade.enums import SlackReactionKind
from products.slack_app.backend.facade.types import SlackReactionChoice, SlackResolvedReaction
from products.slack_app.backend.services.reaction_settings import parse_reactions, resolve_reactions

WORKING = SlackReactionKind.WORKING
DONE = SlackReactionKind.DONE


class TestReactionSettings(SimpleTestCase):
    def test_nothing_stored_keeps_todays_behavior(self) -> None:
        assert resolve_reactions({}, {}) == {
            SlackReactionKind.WORKING: SlackResolvedReaction(emoji="eyes", enabled=True),
            SlackReactionKind.DONE: SlackResolvedReaction(emoji="white_check_mark", enabled=False),
            SlackReactionKind.ERROR: SlackResolvedReaction(emoji="warning", enabled=False),
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
