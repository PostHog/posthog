from typing import cast

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts.backend.destination_configs import (
    slack_body as _slack_body,
    teams_text as _teams_text,
)
from products.logs.backend.alert_destinations import (
    EVENT_KIND_CONFIG,
    EVENT_KINDS,
    AlertDestinationData,
    AlertDestinationValidationError,
    DestinationType,
    EventKind,
    validate_destination_data,
)


class TestDestinationValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("lookalike_host", "https://discord.com.example.com/api/webhooks/123/token"),
            ("http_scheme", "http://discord.com/api/webhooks/123/token"),
            ("explicit_port", "https://discord.com:443/api/webhooks/123/token"),
            ("missing_id", "https://discord.com/api/webhooks//token"),
            ("missing_token", "https://discord.com/api/webhooks/123"),
            ("extra_path", "https://discord.com/api/webhooks/123/token/extra"),
            ("query_string", "https://discord.com/api/webhooks/123/token?wait=true"),
        ]
    )
    def test_rejects_invalid_discord_webhook_urls(self, _name: str, webhook_url: str) -> None:
        with self.assertRaises(AlertDestinationValidationError) as error:
            validate_destination_data({"type": DestinationType.DISCORD, "webhook_url": webhook_url})

        assert error.exception.field == "webhook_url"
        assert error.exception.message == (
            "Enter a Discord webhook URL in the format https://discord.com/api/webhooks/{id}/{token}."
        )

    def test_accepts_discord_webhook_url_with_required_components(self) -> None:
        validate_destination_data(
            {"type": DestinationType.DISCORD, "webhook_url": "https://discord.com/api/webhooks/123/token"}
        )

    @parameterized.expand(
        [
            (
                "multiple_slack_fields",
                {"type": DestinationType.SLACK},
                None,
                "Slack destinations require slack_workspace_id and slack_channel_id.",
            ),
            (
                "discord_webhook_url",
                {"type": DestinationType.DISCORD},
                "webhook_url",
                "webhook_url is required for Discord destinations.",
            ),
        ]
    )
    def test_reports_missing_destination_fields(
        self,
        _name: str,
        data: AlertDestinationData,
        expected_field: str | None,
        expected_message: str,
    ) -> None:
        with self.assertRaises(AlertDestinationValidationError) as error:
            validate_destination_data(data)

        assert error.exception.field == expected_field
        assert error.exception.message == expected_message

    def test_reports_unsupported_destination_type(self) -> None:
        data = cast(AlertDestinationData, {"type": "email"})

        with self.assertRaises(AlertDestinationValidationError) as error:
            validate_destination_data(data)

        assert error.exception.field == "type"
        assert error.exception.message == (
            "Choose a supported destination type: Slack (slack), Discord (discord), Webhook (webhook), "
            "Microsoft Teams (teams)."
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
        assert f"[{spec.primary_action_label}]({spec.primary_action_url})" in text
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
