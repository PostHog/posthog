import json

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration import Integration

from products.slack_app.backend.services.welcome_messages import (
    build_channel_welcome,
    build_install_welcome,
    build_team_join_welcome,
)

BUILDERS = [
    ("channel", build_channel_welcome),
    ("team_join", build_team_join_welcome),
    ("install", build_install_welcome),
]


def _integration(**config) -> Integration:
    # Unsaved: every builder reads `config` and `integration_id` only.
    return Integration(kind="slack", integration_id="T_WELCOME", config=config)


class TestWelcomeMessages(SimpleTestCase):
    @parameterized.expand(BUILDERS)
    def test_links_the_home_tab_when_the_app_id_is_known(self, _name, build):
        _, blocks = build(_integration(app_id="A_WELCOME"))

        assert "<slack://app?team=T_WELCOME&id=A_WELCOME&tab=home|" in json.dumps(blocks)

    @parameterized.expand(BUILDERS)
    def test_names_the_home_tab_in_plain_words_without_an_app_id(self, _name, build):
        _, blocks = build(_integration())
        rendered = json.dumps(blocks)

        assert "Home tab" in rendered
        assert "slack://" not in rendered
        assert "None" not in rendered

    @parameterized.expand(BUILDERS)
    def test_carries_fallback_text_for_the_notification(self, _name, build):
        text, blocks = build(_integration(app_id="A_WELCOME"))

        assert text
        # Slack drops `blocks` from a notification preview, so text that leaked mrkdwn or a
        # link would show as raw markup on a lock screen.
        assert "<" not in text and "*" not in text and "`" not in text
        assert blocks
