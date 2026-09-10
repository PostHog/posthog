from typing import Any, cast

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationValidationError,
    DestinationType,
)
from products.alerts.backend.facade.destinations import build_alert_destination_config, validate_destination_data
from products.logs.backend.alert_destinations import (
    EVENT_KIND_CONFIG,
    EVENT_KINDS,
    LOGS_ALERT_SLACK_CONTEXT_ELEMENTS,
    LOGS_DESTINATION_TYPES,
    EventKind,
)


class TestDestinationValidation(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "multiple_slack_fields",
                {"type": DestinationType.SLACK},
                None,
                "Slack destinations require slack_workspace_id and slack_channel_id.",
            ),
            (
                "teams_webhook_url",
                {"type": DestinationType.TEAMS},
                "webhook_url",
                "webhook_url is required for Microsoft Teams destinations.",
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
            validate_destination_data(data, allowed_destination_types=LOGS_DESTINATION_TYPES)

        assert error.exception.field == expected_field
        assert error.exception.message == expected_message

    def test_reports_unsupported_destination_type(self) -> None:
        data = cast(AlertDestinationData, {"type": "email"})

        with self.assertRaises(AlertDestinationValidationError) as error:
            validate_destination_data(data, allowed_destination_types=LOGS_DESTINATION_TYPES)

        assert error.exception.field == "type"
        assert error.exception.message == (
            "Choose a supported destination type: Slack (slack), Webhook (webhook), Microsoft Teams (teams)."
        )


SLACK_DATA = cast(
    AlertDestinationData, {"type": DestinationType.SLACK, "slack_workspace_id": 1, "slack_channel_id": "C-ENG"}
)
TEAMS_DATA = cast(AlertDestinationData, {"type": DestinationType.TEAMS, "webhook_url": "https://example.com/hook"})


def destination_inputs(kind: EventKind, data: AlertDestinationData) -> dict[str, Any]:
    config = build_alert_destination_config(
        spec=EVENT_KIND_CONFIG[kind],
        alert_id="alert-1",
        alert_name="Checkout errors",
        data=data,
        slack_context_elements=LOGS_ALERT_SLACK_CONTEXT_ELEMENTS,
    )
    return config.payload["inputs"]


class TestRenderedDestinationContent(SimpleTestCase):
    @parameterized.expand([(kind,) for kind in EVENT_KINDS])
    def test_slack_body_puts_every_detail_on_its_own_line(self, kind: EventKind) -> None:
        spec = EVENT_KIND_CONFIG[kind]
        blocks = destination_inputs(kind, SLACK_DATA)["blocks"]["value"]
        body = blocks[1]["text"]["text"]

        lines = body.split("\n")
        assert lines == [f"*{label}:* {value}" for label, value in spec.details]
        # Slack mrkdwn bolds with one asterisk, so a `**` pair would render as literal text.
        assert "**" not in body

    @parameterized.expand([(kind,) for kind in EVENT_KINDS])
    def test_teams_text_is_adaptive_card_markdown(self, kind: EventKind) -> None:
        spec = EVENT_KIND_CONFIG[kind]
        text = destination_inputs(kind, TEAMS_DATA)["text"]["value"]

        assert text.startswith(f"**{spec.header}**")
        for label, value in spec.details:
            assert f"**{label}:** {value}" in text
        assert f"[{spec.primary_action_label}]({spec.primary_action_url})" in text
        # An Adaptive Card renders a single asterisk literally, so every one must be part of a pair.
        assert "*" not in text.replace("**", "")
        # Its paragraphs need exactly one blank line between them; a stacked one renders as a gap.
        assert "\n\n\n" not in text
