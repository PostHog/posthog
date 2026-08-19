import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.waydev import WaydevSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.waydev.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.waydev.source import WaydevSource
from products.warehouse_sources.backend.temporal.data_imports.sources.waydev.waydev import WaydevResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestWaydevSource:
    def setup_method(self) -> None:
        self.source = WaydevSource()
        self.team_id = 123
        self.config = WaydevSourceConfig(api_key="key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.WAYDEV

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Waydev"
        assert config.label == "Waydev"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/waydev.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/waydev"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_api_version(self) -> None:
        assert self.source.supported_versions == ("v2",)
        assert self.source.default_version == "v2"
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.waydev.co/v2/incidents",
            "Unauthorized",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.waydev.co/v2/incidents",
            "500 Server Error: Internal Server Error for url: https://api.waydev.co/v2/metrics",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_all_full_refresh(self) -> None:
        # Neither endpoint documents a server-side timestamp filter.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Incidents"])
        assert len(schemas) == 1
        assert schemas[0].name == "Incidents"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self) -> None:
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Waydev API token"),
            ((False, 403), False, "Could not connect to Waydev with the provided API token"),
            ((False, None), False, "Could not connect to Waydev with the provided API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.waydev.source.validate_waydev_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, int | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is WaydevResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.waydev.source.waydev_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_waydev_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Incidents"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        manager = mock.MagicMock()
        mock_waydev_source.return_value.name = "Incidents"
        mock_waydev_source.return_value.column_hints = None

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        mock_waydev_source.assert_called_once_with(
            api_key="key",
            endpoint="Incidents",
            team_id=self.team_id,
            job_id="job-1",
            resumable_source_manager=manager,
        )
        assert response.primary_keys == ["id"]
        assert response.name == "Incidents"
