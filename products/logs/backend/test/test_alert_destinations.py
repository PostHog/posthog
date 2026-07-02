from django.test import SimpleTestCase

from parameterized import parameterized

from products.logs.backend.alert_destinations import EVENT_KIND_CONFIG, EVENT_KINDS, EventKind

from common.alerting.destinations import (
    slack_body as _slack_body,
    teams_text as _teams_text,
)


class TestSlackBody(SimpleTestCase):
    @parameterized.expand([(kind,) for kind in EVENT_KINDS])
    def test_body_is_slack_mrkdwn(self, kind: EventKind) -> None:
        spec = EVENT_KIND_CONFIG[kind]
        body = _slack_body(spec)
        lines = body.split("\n")
        assert len(lines) == len(spec.details)
        for line, (label, value) in zip(lines, spec.details):
            # Slack mrkdwn bold label, then the plain-text value.
            assert line == f"*{label}:* {value}"
        # Detail values are plain text — bold markers come only from the renderer.
        assert "**" not in body

    def test_multi_detail_body_renders_one_line_per_detail(self) -> None:
        body = _slack_body(EVENT_KIND_CONFIG["broken"])
        assert body == (
            "*Reason:* {event.properties.consecutive_failures} consecutive check failures.\n"
            "*Last error:* {event.properties.last_error_message}"
        )


class TestTeamsText(SimpleTestCase):
    @parameterized.expand([(kind,) for kind in EVENT_KINDS])
    def test_text_is_adaptive_card_markdown(self, kind: EventKind) -> None:
        spec = EVENT_KIND_CONFIG[kind]
        text = _teams_text(spec)
        # Bold header, every detail label bolded, the action rendered as an inline markdown link.
        assert text.startswith(f"**{spec.header}**")
        for label, value in spec.details:
            assert f"**{label}:** {value}" in text
        assert f"[{spec.button_label}]({spec.button_url})" in text
        # Every asterisk must belong to a `**` pair — no Slack-style single-asterisk bold.
        assert "*" not in text.replace("**", "")

    def test_multi_detail_text_separates_paragraphs_with_blank_lines(self) -> None:
        text = _teams_text(EVENT_KIND_CONFIG["broken"])
        assert (
            "**Reason:** {event.properties.consecutive_failures} consecutive check failures.\n\n"
            "**Last error:** {event.properties.last_error_message}"
        ) in text
        # Adaptive Card paragraphs need exactly one blank line — never stacked blank lines.
        assert "\n\n\n" not in text
