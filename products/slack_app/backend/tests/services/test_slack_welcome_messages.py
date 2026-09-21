import json
from typing import Any

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration import Integration

from products.slack_app.backend.services.slack_welcome_messages import (
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


def _rendered(blocks: list[dict[str, Any]]) -> str:
    """The message as a reader sees it, so a copy edit diffs as prose rather than as JSON."""
    lines = []
    for block in blocks:
        if block["type"] == "section":
            lines.append(block["text"]["text"])
        elif block["type"] == "context":
            lines.append(block["elements"][0]["text"])
        elif block["type"] == "actions":
            lines.append(" ".join(f"[{e['text']['text']}]({e['url']})" for e in block["elements"]))
    return "\n\n".join(lines)


# Keyed by name rather than by builder so each snapshot is filed under a readable id.
@pytest.mark.parametrize("name", [name for name, _ in BUILDERS])
def test_welcome_copy(name, snapshot):
    build = dict(BUILDERS)[name]
    text, blocks = build(_integration(app_id="A_WELCOME"))

    assert snapshot == f"{text}\n\n---\n\n{_rendered(blocks)}"


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
    def test_asks_for_a_rating(self, _name, build):
        _, blocks = build(_integration(app_id="A_WELCOME"))
        rendered = json.dumps(blocks)

        assert ":thumbsup:" in rendered and ":thumbsdown:" in rendered

    @parameterized.expand(BUILDERS)
    def test_carries_fallback_text_for_the_notification(self, _name, build):
        text, blocks = build(_integration(app_id="A_WELCOME"))

        assert text
        # Slack drops `blocks` from a notification preview, so text that leaked mrkdwn or a
        # link would show as raw markup on a lock screen.
        assert "<" not in text and "*" not in text and "`" not in text
        assert blocks
