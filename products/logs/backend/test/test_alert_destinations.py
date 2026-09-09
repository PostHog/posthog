from typing import cast

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationValidationError,
    DestinationType,
)
from products.alerts.backend.facade.destinations import validate_destination_data
from products.logs.backend.alert_destinations import LOGS_DESTINATION_TYPES


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
