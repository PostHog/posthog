from datetime import UTC, date, datetime
from typing import cast

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.asaas.asaas import (
    PRODUCTION_BASE_URL,
    SANDBOX_BASE_URL,
    AsaasResumeConfig,
    asaas_source,
    base_url,
    format_date_param,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asaas.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.asaas.source import AsaasSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.asaas import AsaasSourceConfig

_INCREMENTAL_ENDPOINTS = {"Payments", "Transfers"}
_FULL_REFRESH_ENDPOINTS = {"Customers", "Subscriptions", "Installments"}

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.asaas.source.validate_asaas_credentials"
)
ASAAS_SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.asaas.source.asaas_source"
REST_API_RESOURCE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.asaas.asaas.rest_api_resource"
)
SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.asaas.asaas.make_tracked_session"


class TestBaseUrl:
    @parameterized.expand(
        [
            ("production", PRODUCTION_BASE_URL),
            ("sandbox", SANDBOX_BASE_URL),
            ("unknown_defaults_to_sandbox", SANDBOX_BASE_URL),
        ]
    )
    def test_resolves_environment(self, environment: str, expected: str) -> None:
        assert base_url(environment) == expected


class TestFormatDateParam:
    @parameterized.expand(
        [
            ("datetime_utc", datetime(2026, 1, 15, 10, 30, tzinfo=UTC), "2026-01-15"),
            ("naive_datetime", datetime(2026, 1, 15, 10, 30), "2026-01-15"),
            ("date_object", date(2026, 1, 15), "2026-01-15"),
            ("date_string_passthrough", "2026-01-15", "2026-01-15"),
            ("datetime_string_truncated", "2026-01-15T10:30:00Z", "2026-01-15"),
        ]
    )
    def test_formats_to_date_only_string(self, _name: str, value, expected: str) -> None:
        assert format_date_param(value) == expected


class TestGetResource:
    @parameterized.expand(sorted(_INCREMENTAL_ENDPOINTS))
    def test_incremental_endpoint_adds_date_filter_when_requested(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        endpoint_config = cast(Endpoint, resource["endpoint"])
        params = endpoint_config["params"]
        assert params is not None
        assert "dateCreated[ge]" in params
        assert params["dateCreated[ge]"]["type"] == "incremental"

    @parameterized.expand(sorted(_INCREMENTAL_ENDPOINTS))
    def test_incremental_endpoint_omits_filter_when_not_requested(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)

        assert resource["write_disposition"] == "replace"
        endpoint_config = cast(Endpoint, resource["endpoint"])
        assert endpoint_config["params"] == {}

    @parameterized.expand(sorted(_FULL_REFRESH_ENDPOINTS))
    def test_full_refresh_endpoint_never_adds_date_filter(self, endpoint: str) -> None:
        # These endpoints don't document a server-side date filter; requesting incremental
        # must not fabricate one that the API would silently ignore or reject.
        resource = get_resource(endpoint, should_use_incremental_field=True)

        assert resource["write_disposition"] == "replace"
        endpoint_config = cast(Endpoint, resource["endpoint"])
        assert endpoint_config["params"] == {}

    def test_path_and_selector_match_every_endpoint(self) -> None:
        for endpoint in ENDPOINTS:
            resource = get_resource(endpoint, should_use_incremental_field=False)
            endpoint_config = cast(Endpoint, resource["endpoint"])
            assert endpoint_config["data_selector"] == "data[*]"
            path = endpoint_config["path"]
            assert path is not None
            assert path.startswith("/v3/")
            assert resource["table_format"] == "delta"


class TestAsaasSourceResumeBehavior:
    """`asaas_source` plumbing: resume seeding and checkpoint persistence."""

    def _run(self, manager: mock.MagicMock, *, should_use_incremental_field: bool = False):
        with mock.patch(REST_API_RESOURCE_PATCH) as mock_rest_api_resource:
            mock_rest_api_resource.return_value = mock.MagicMock(name="Payments")
            asaas_source(
                api_key="test-key",
                environment="production",
                endpoint="Payments",
                team_id=123,
                job_id="job-1",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                should_use_incremental_field=should_use_incremental_field,
            )
            return mock_rest_api_resource

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        mock_rest_api_resource = self._run(manager)

        manager.load_state.assert_not_called()
        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] is None

    def test_seeds_initial_offset_from_saved_state(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = AsaasResumeConfig(offset=200)

        mock_rest_api_resource = self._run(manager)

        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"offset": 200}

    def test_resume_hook_saves_offset_when_present(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        mock_rest_api_resource = self._run(manager)
        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]

        resume_hook({"offset": 300})

        manager.save_state.assert_called_once_with(AsaasResumeConfig(offset=300))

    def test_resume_hook_skips_save_on_terminal_page(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        mock_rest_api_resource = self._run(manager)
        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]

        resume_hook(None)

        manager.save_state.assert_not_called()

    @parameterized.expand([("production", PRODUCTION_BASE_URL), ("sandbox", SANDBOX_BASE_URL)])
    def test_client_config_targets_the_selected_environment(self, environment: str, expected_base_url: str) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with mock.patch(REST_API_RESOURCE_PATCH) as mock_rest_api_resource:
            mock_rest_api_resource.return_value = mock.MagicMock()
            asaas_source(
                api_key="test-key",
                environment=environment,
                endpoint="Payments",
                team_id=123,
                job_id="job-1",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
            )
            config = mock_rest_api_resource.call_args.args[0]
            assert config["client"]["base_url"] == expected_base_url
            assert config["client"]["auth"] == {
                "type": "api_key",
                "name": "access_token",
                "api_key": "test-key",
                "location": "header",
            }


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False)])
    def test_status_code_maps_to_validity(self, status_code: int, expected: bool) -> None:
        with mock.patch(SESSION_PATCH) as mock_make_session:
            mock_response = mock.MagicMock()
            mock_response.status_code = status_code
            mock_make_session.return_value.get.return_value = mock_response

            assert validate_credentials("test-key", "production") is expected

    def test_requests_the_selected_environment_host(self) -> None:
        with mock.patch(SESSION_PATCH) as mock_make_session:
            mock_response = mock.MagicMock()
            mock_response.status_code = 200
            mock_make_session.return_value.get.return_value = mock_response

            validate_credentials("test-key", "sandbox")

            called_url = mock_make_session.return_value.get.call_args.args[0]
            assert called_url.startswith(SANDBOX_BASE_URL)
            headers = mock_make_session.return_value.get.call_args.kwargs["headers"]
            assert headers == {"access_token": "test-key"}


class TestAsaasSource:
    def setup_method(self) -> None:
        self.source = AsaasSource()
        self.team_id = 123
        self.config = AsaasSourceConfig(api_key="test-key", environment="production")

    def test_api_version_metadata(self) -> None:
        assert self.source.supported_versions == ("v3",)
        assert self.source.default_version == "v3"
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.asaas.com/v3/customers?limit=1",
            "403 Client Error: Forbidden for url: https://api.asaas.com/v3/payments?limit=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.asaas.com/v3/payments",
            "500 Server Error: Internal Server Error for url: https://api.asaas.com/v3/payments",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @parameterized.expand([(True, True, None), (False, False, "Invalid credentials")])
    def test_validate_credentials(self, mock_return: bool, expected_valid: bool, expected_message) -> None:
        with mock.patch(VALIDATE_PATCH, return_value=mock_return) as mock_validate:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert (is_valid, error_message) == (expected_valid, expected_message)
        mock_validate.assert_called_once_with("test-key", "production")

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Payments"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = mock.MagicMock()

        with mock.patch(ASAAS_SOURCE_PATCH) as mock_asaas_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_asaas_source.assert_called_once()
        kwargs = mock_asaas_source.call_args.kwargs
        assert kwargs["api_key"] == "test-key"
        assert kwargs["environment"] == "production"
        assert kwargs["endpoint"] == "Payments"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"

    def test_source_for_pipeline_omits_cursor_when_not_incremental(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Customers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"

        with mock.patch(ASAAS_SOURCE_PATCH) as mock_asaas_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_asaas_source.call_args.kwargs["db_incremental_field_last_value"] is None
