import pytest
from unittest.mock import MagicMock, patch

import requests

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spotlercrm import (
    SpotlerCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.source import SpotlerCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.spotlercrm import (
    SpotlerCRMResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSpotlerCRMSource:
    def setup_method(self) -> None:
        self.source = SpotlerCRMSource()
        self.config = SpotlerCRMSourceConfig(access_token="test-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SPOTLERCRM

    def test_source_is_released_with_alpha_status(self) -> None:
        source_config = self.source.get_source_config

        assert not source_config.unreleasedSource
        assert source_config.releaseStatus == ReleaseStatus.ALPHA

    def test_source_config_asks_for_a_secret_access_token(self) -> None:
        fields = self.source.get_source_config.fields

        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "access_token"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_get_schemas_lists_every_endpoint_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)

        assert [s.name for s in schemas] == list(ENDPOINTS)
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["Accounts", "Contacts"])

        assert {s.name for s in schemas} == {"Accounts", "Contacts"}

    @pytest.mark.parametrize(
        ("endpoint", "expected_default"),
        [
            ("Accounts", True),
            ("Campaigns", False),  # Marketing tool add-on
            ("Cases", False),  # Service & Support tool add-on
        ],
    )
    def test_addon_gated_endpoints_start_disabled(self, endpoint: str, expected_default: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}

        assert schemas[endpoint].should_sync_default is expected_default

    def test_validate_credentials_uses_config_token(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.source.validate_spotlercrm_credentials"
        ) as validate:
            validate.return_value = (True, None)

            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)
            validate.assert_called_once_with("test-token")

    def test_source_for_pipeline_plumbs_schema_and_manager(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "Contacts"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.source.spotlercrm_source"
        ) as transport:
            self.source.source_for_pipeline(self.config, manager, inputs)

            transport.assert_called_once_with(
                access_token="test-token",
                endpoint="Contacts",
                team_id=7,
                job_id="job-1",
                resumable_source_manager=manager,
            )

    def test_resumable_source_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert manager._data_class is SpotlerCRMResumeConfig

    def test_auth_error_from_live_api_matches_non_retryable_pattern(self) -> None:
        # The live API answers 403 for a bad token (verified with curl); make sure the
        # HTTPError string requests raises for it maps to a non-retryable error.
        response = requests.Response()
        response.status_code = 403
        response.url = "https://apiv4.reallysimplesystems.com/accounts"
        response.reason = "Forbidden"

        with pytest.raises(requests.HTTPError) as exc_info:
            response.raise_for_status()

        non_retryable = self.source.get_non_retryable_errors()
        assert any(pattern in str(exc_info.value) for pattern in non_retryable)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions.keys()) == set(ENDPOINTS)
