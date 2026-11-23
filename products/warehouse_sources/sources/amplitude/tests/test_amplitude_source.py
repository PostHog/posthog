from typing import Any

import time_machine
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.amplitude._config import AmplitudeSourceConfig
from products.warehouse_sources.sources.amplitude.amplitude import AMPLITUDE_INVALID_ARCHIVE_ERROR
from products.warehouse_sources.sources.amplitude.settings import (
    DEPLOYMENTS_ENDPOINT,
    EVENTS_ENDPOINT,
    EXPERIMENTS_ENDPOINT,
    FLAGS_ENDPOINT,
    LOOKUP_TABLES_ENDPOINT,
)
from products.warehouse_sources.sources.amplitude.source import (
    AMPLITUDE_SLOW_RESPONSE_MESSAGE,
    MISSING_MANAGEMENT_KEY_MESSAGE,
    AmplitudeSource,
)
from products.warehouse_sources.sources.sdk.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    error_message_matches,
    scripted_network,
)


class TestAmplitudeSource:
    def setup_method(self) -> None:
        self.source = AmplitudeSource()
        self.team_id = 123
        self.config = AmplitudeSourceConfig(api_key="key", secret_key="secret", region="us")

    @time_machine.travel("2026-06-04 12:00:00", tick=False)
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            EVENTS_ENDPOINT,
            always(ScriptedResponse(status=404)),
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        # When the user isn't running incrementally, no watermark should leak through.
        assert result.requests[0].param("start") == "20260505T10"
        assert result.raised is None

    def test_invalid_archive_error_is_classified_retryable(self) -> None:
        error_message = f"{AMPLITUDE_INVALID_ARCHIVE_ERROR}: url=https://amplitude.com/api/2/export?start=20260101T00&end=20260101T23"
        assert any(pattern in error_message for pattern in self.source.get_retryable_errors())

    def test_exhausted_read_timeout_stays_retryable_with_slow_response_copy(self) -> None:
        with mock.patch("tenacity.nap.time.sleep"):
            result = SourceDriver(self.source, self.config).run(
                EVENTS_ENDPOINT, always(TimeoutError("timed out")), should_use_incremental_field=False
            )

        error_message = str(result.raised)
        assert error_message_matches(error_message, self.source.get_retryable_errors())
        assert not error_message_matches(error_message, self.source.get_non_retryable_errors().keys())
        messages = [
            message
            for pattern, message in self.source.get_retry_exhausted_errors().items()
            if error_message_matches(error_message, [pattern])
        ]
        assert messages == [AMPLITUDE_SLOW_RESPONSE_MESSAGE]

    @parameterized.expand(
        [
            ("without_key", None, MISSING_MANAGEMENT_KEY_MESSAGE),
            ("with_key", "mgmt-key", None),
        ]
    )
    def test_endpoint_permissions_flag_management_tables(
        self, _name: str, management_api_key: str | None, expected_management_reason: str | None
    ) -> None:
        config = AmplitudeSourceConfig(
            api_key="key", secret_key="secret", region="us", management_api_key=management_api_key
        )
        endpoints = [
            EVENTS_ENDPOINT,
            LOOKUP_TABLES_ENDPOINT,
            EXPERIMENTS_ENDPOINT,
            FLAGS_ENDPOINT,
            DEPLOYMENTS_ENDPOINT,
        ]

        permissions = self.source.get_endpoint_permissions(config, self.team_id, endpoints)

        assert permissions == {
            EVENTS_ENDPOINT: None,
            LOOKUP_TABLES_ENDPOINT: None,
            EXPERIMENTS_ENDPOINT: expected_management_reason,
            FLAGS_ENDPOINT: expected_management_reason,
            DEPLOYMENTS_ENDPOINT: expected_management_reason,
        }

    @parameterized.expand(
        [
            # A management table without a key fails before any request.
            ("management_table_without_key", FLAGS_ENDPOINT, None, [], False, []),
            # A management table checks only the management key.
            ("management_table_with_key", FLAGS_ENDPOINT, "mgmt-key", [200], True, ["/api/1/deployments"]),
            ("management_table_rejected_key", FLAGS_ENDPOINT, "mgmt-key", [401], False, ["/api/1/deployments"]),
            # At create, a key the user typed is checked after the project keys.
            ("create_with_key", None, "mgmt-key", [200, 200], True, ["/api/2/annotations", "/api/1/deployments"]),
            ("create_rejected_key", None, "mgmt-key", [200, 403], False, ["/api/2/annotations", "/api/1/deployments"]),
            ("create_without_key", None, None, [200], True, ["/api/2/annotations"]),
            # A project key failure is reported without checking the management key.
            ("create_bad_project_keys", None, "mgmt-key", [401], False, ["/api/2/annotations"]),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        schema_name: str | None,
        management_api_key: str | None,
        statuses: list[int],
        expected_valid: bool,
        expected_paths: list[str],
    ) -> None:
        config = AmplitudeSourceConfig(
            api_key="key", secret_key="secret", region="us", management_api_key=management_api_key
        )
        responses: list[Any] = [ScriptedResponse(status=status, json={}) for status in statuses]

        with scripted_network(responses) as network:
            is_valid, message = self.source.validate_credentials(config, self.team_id, schema_name=schema_name)

        assert [request.path for request in network.requests_log] == expected_paths
        assert is_valid is expected_valid
        assert (message is None) is expected_valid
