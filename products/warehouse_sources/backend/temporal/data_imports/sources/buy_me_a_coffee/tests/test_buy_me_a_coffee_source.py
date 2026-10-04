from unittest.mock import patch

from django.test import SimpleTestCase

import structlog
from parameterized import parameterized
from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.buy_me_a_coffee.source import BuyMeACoffeeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buymeacoffee import (
    BuyMeACoffeeSourceConfig,
)


class TestBuyMeACoffeeSource(SimpleTestCase):
    def test_unknown_credential_schema_is_rejected_without_http(self) -> None:
        with patch("requests.sessions.Session.send") as send:
            valid, error = BuyMeACoffeeSource().validate_credentials(
                BuyMeACoffeeSourceConfig(access_token="test-token"), team_id=1, schema_name="unknown"
            )
        assert not valid
        assert error is not None and "Unknown Buy Me a Coffee table" in error
        send.assert_not_called()

    def test_incremental_sync_is_rejected_instead_of_silently_full_refreshing(self) -> None:
        source = BuyMeACoffeeSource()
        inputs = SourceInputs(
            schema_name="supporters",
            schema_id="schema",
            source_id="source",
            team_id=1,
            should_use_incremental_field=True,
            db_incremental_field_last_value=100,
            db_incremental_field_earliest_value=None,
            incremental_field="support_id",
            incremental_field_type=None,
            job_id="job",
            logger=structlog.get_logger(),
            reset_pipeline=False,
        )
        with patch("requests.sessions.Session.send") as send:
            with self.assertRaisesRegex(ValueError, "only supports full refresh"):
                source.source_for_pipeline(
                    BuyMeACoffeeSourceConfig(access_token="test-token"),
                    source.get_resumable_source_manager(inputs),
                    inputs,
                )
        send.assert_not_called()

    @parameterized.expand(
        [
            (401, "Unauthorized", True),
            (403, "Forbidden", True),
            (429, "Too Many Requests", False),
            (500, "Internal Server Error", False),
        ]
    )
    def test_sync_errors_disable_only_invalid_credentials(self, status: int, reason: str, terminal: bool) -> None:
        response = Response()
        response.status_code = status
        response.reason = reason
        response.url = "https://developers.buymeacoffee.com/api/v1/supporters"
        try:
            response.raise_for_status()
        except HTTPError as error:
            assert error_message_matches(str(error), BuyMeACoffeeSource().get_non_retryable_errors()) is terminal
