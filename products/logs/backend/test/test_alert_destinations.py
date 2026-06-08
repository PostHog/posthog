from django.test import SimpleTestCase

from parameterized import parameterized

from products.logs.backend.alert_destinations import (
    EVENT_KIND_CONFIG,
    EVENT_KINDS,
    _slack_to_teams_markdown,
    _teams_text,
)


class TestSlackToTeamsMarkdown(SimpleTestCase):
    @parameterized.expand(
        [
            ("single_bold", "*Threshold breached:* 5 logs", "**Threshold breached:** 5 logs"),
            ("plain_text_unchanged", "No markers here", "No markers here"),
            ("newline_widened", "*Reason:* failed\n*Last error:* boom", "**Reason:** failed\n\n**Last error:** boom"),
            ("multiple_bolds", "*a* and *b*", "**a** and **b**"),
        ]
    )
    def test_converts_slack_mrkdwn(self, _name: str, slack_text: str, expected: str) -> None:
        assert _slack_to_teams_markdown(slack_text) == expected


class TestTeamsText(SimpleTestCase):
    @parameterized.expand([(kind,) for kind in EVENT_KINDS])
    def test_text_is_adaptive_card_markdown(self, kind: str) -> None:
        spec = EVENT_KIND_CONFIG[kind]
        text = _teams_text(spec)
        # Bold header, the action rendered as an inline markdown link, and no stray Slack-style single asterisks.
        assert text.startswith("**")
        assert f"[{spec.button_label}]({spec.button_url})" in text
        # Every asterisk must belong to a `**` pair — no leftover Slack single-asterisk bold.
        assert "*" not in text.replace("**", "")
