import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tyntecsms import (
    TyntecSMSSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.settings import (
    CONTACTS,
    ENDPOINTS,
    MESSAGE_STATUS,
    PHONE_NUMBERS,
    PHONE_REGISTRATIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.source import TyntecSMSSource


class TestTyntecSMSSource:
    def setup_method(self) -> None:
        self.source = TyntecSMSSource()

    def test_get_schemas_are_full_refresh_only(self) -> None:
        # tyntec has no server-side timestamp filters, so no table may advertise incremental sync.
        schemas = self.source.get_schemas(TyntecSMSSourceConfig(api_key="key"), team_id=1)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)

    @pytest.mark.parametrize(
        ("endpoint", "expected_default"),
        [
            (MESSAGE_STATUS, True),
            # BYON tables default off: the live gateway 404s them on accounts without the
            # BYON service, and a default-on table would fail every fresh source's first sync.
            (CONTACTS, False),
            (PHONE_NUMBERS, False),
            (PHONE_REGISTRATIONS, False),
        ],
    )
    def test_should_sync_defaults(self, endpoint: str, expected_default: bool) -> None:
        schemas = self.source.get_schemas(TyntecSMSSourceConfig(api_key="key"), team_id=1)
        schema = next(s for s in schemas if s.name == endpoint)

        assert schema.should_sync_default is expected_default

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(TyntecSMSSourceConfig(api_key="key"), team_id=1, names=[CONTACTS])

        assert [schema.name for schema in schemas] == [CONTACTS]

    def test_validate_credentials_rejects_empty_key_without_network(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.source.validate_tyntec_credentials"
        ) as mock_validate:
            valid, error = self.source.validate_credentials(TyntecSMSSourceConfig(api_key=""), team_id=1)

        assert valid is False
        assert error is not None
        mock_validate.assert_not_called()

    @pytest.mark.parametrize(("api_accepts_key", "expected_valid"), [(True, True), (False, False)])
    def test_validate_credentials_maps_helper_result(self, api_accepts_key: bool, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.source.validate_tyntec_credentials",
            return_value=api_accepts_key,
        ):
            valid, error = self.source.validate_credentials(TyntecSMSSourceConfig(api_key="key"), team_id=1)

        assert valid is expected_valid
        assert (error is None) is expected_valid

    def test_source_for_pipeline_plumbs_config_and_inputs(self) -> None:
        config = TyntecSMSSourceConfig(api_key="key", request_ids="id-1, id-2")
        inputs = MagicMock(spec=SourceInputs)
        inputs.schema_name = MESSAGE_STATUS
        inputs.team_id = 42
        inputs.job_id = "job-1"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.source.tyntec_sms_source"
        ) as mock_source:
            response = self.source.source_for_pipeline(config, inputs)

        mock_source.assert_called_once_with(
            api_key="key",
            endpoint=MESSAGE_STATUS,
            team_id=42,
            job_id="job-1",
            request_ids="id-1, id-2",
        )
        assert response is mock_source.return_value

    @pytest.mark.parametrize(
        "url",
        [
            "https://api.tyntec.com/messaging/v1/messages/some-id",
            "https://api.tyntec.com/byon/contacts/v1",
        ],
    )
    @pytest.mark.parametrize(("status_code", "reason"), [(401, "Unauthorized"), (403, "Forbidden")])
    def test_auth_http_errors_are_non_retryable(self, status_code: int, reason: str, url: str) -> None:
        # A bad key must permanently fail the job; a message-format mismatch here means endless retries.
        response = requests.Response()
        response.status_code = status_code
        response.url = url
        response.reason = reason

        with pytest.raises(requests.HTTPError) as exc_info:
            response.raise_for_status()

        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(pattern in str(exc_info.value) for pattern in non_retryable_errors)
