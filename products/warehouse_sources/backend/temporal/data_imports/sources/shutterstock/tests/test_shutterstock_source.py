from typing import Literal

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shutterstock import (
    ShutterstockAuthMethodConfig,
    ShutterstockSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.shutterstock import (
    ShutterstockResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.source import (
    ShutterstockSource,
    _auth_from_config,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _basic_config(**auth_overrides: str) -> ShutterstockSourceConfig:
    return ShutterstockSourceConfig(
        auth_method=ShutterstockAuthMethodConfig(
            selection="api_key", consumer_key="ck", consumer_secret="cs", **auth_overrides
        )
    )


class TestShutterstockSource:
    def setup_method(self) -> None:
        self.source = ShutterstockSource()
        self.team_id = 123
        self.config = _basic_config()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SHUTTERSTOCK

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Shutterstock"
        assert config.label == "Shutterstock"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/shutterstock"

    def test_auth_select_offers_both_credential_types_with_secret_inputs(self) -> None:
        config = self.source.get_source_config
        select = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig))

        assert select.name == "auth_method"
        assert [option.value for option in select.options] == ["api_key", "access_token"]
        secret_fields = {
            field.name for option in select.options for field in option.fields or [] if getattr(field, "secret", False)
        }
        assert secret_fields == {"consumer_secret", "access_token"}

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.shutterstock.com/v2/images/updated?page=1",
            "403 Client Error: Forbidden for url: https://api.shutterstock.com/v2/images/licenses",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.shutterstock.com/v2/images/updated",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_server_side_filter_endpoints_are_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        # Only the updated feeds and license history expose Shutterstock's server-side
        # `start_date` filter.
        assert incremental == {"images_updated", "videos_updated", "image_licenses", "video_licenses"}

    def test_incremental_schemas_advertise_their_fields(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["image_licenses"].incremental_fields == INCREMENTAL_FIELDS["image_licenses"]
        assert schemas["subscriptions"].incremental_fields == []
        assert schemas["subscriptions"].supports_append is False

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["image_licenses"])
        assert len(schemas) == 1
        assert schemas[0].name == "image_licenses"

    def test_get_canonical_descriptions_keys_match_endpoints(self) -> None:
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical).issubset(set(ENDPOINTS))

    @pytest.mark.parametrize(
        "selection, expected",
        [
            ("api_key", {"consumer_key": "ck", "consumer_secret": "cs", "access_token": None}),
            ("access_token", {"consumer_key": None, "consumer_secret": None, "access_token": "tok"}),
        ],
    )
    def test_auth_from_config_routes_by_selection(
        self, selection: Literal["api_key", "access_token"], expected: dict[str, str | None]
    ) -> None:
        config = ShutterstockSourceConfig(
            auth_method=ShutterstockAuthMethodConfig(
                selection=selection, consumer_key="ck", consumer_secret="cs", access_token="tok"
            )
        )
        auth = _auth_from_config(config)
        assert auth.consumer_key == expected["consumer_key"]
        assert auth.consumer_secret == expected["consumer_secret"]
        assert auth.access_token == expected["access_token"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Shutterstock credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.source.validate_shutterstock_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.source.check_endpoint_access"
    )
    def test_validate_credentials_with_schema_name_reports_scope_reason(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = "needs licenses.view"

        is_valid, error_message = self.source.validate_credentials(
            self.config, self.team_id, schema_name="image_licenses"
        )

        assert is_valid is False
        assert error_message == "needs licenses.view"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.source.check_endpoint_access"
    )
    def test_get_endpoint_permissions_probes_known_endpoints_only(self, mock_check: mock.MagicMock) -> None:
        mock_check.side_effect = lambda auth, endpoint: "blocked" if endpoint == "subscriptions" else None

        permissions = self.source.get_endpoint_permissions(
            self.config, self.team_id, ["subscriptions", "image_categories", "not_an_endpoint"]
        )

        assert permissions == {"subscriptions": "blocked", "image_categories": None, "not_an_endpoint": None}

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ShutterstockResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.source.shutterstock_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_shutterstock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "image_licenses"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_shutterstock_source.call_args.kwargs
        assert kwargs["auth"].consumer_key == "ck"
        assert kwargs["auth"].consumer_secret == "cs"
        assert kwargs["endpoint"] == "image_licenses"
        assert kwargs["team_id"] is inputs.team_id
        assert kwargs["job_id"] is inputs.job_id
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.source.shutterstock_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(
        self, mock_shutterstock_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "subscriptions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_shutterstock_source.call_args.kwargs["db_incremental_field_last_value"] is None
