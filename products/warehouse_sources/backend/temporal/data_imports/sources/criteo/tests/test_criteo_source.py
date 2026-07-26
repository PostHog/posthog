from collections.abc import Iterable
from typing import Any, Optional, cast

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.criteo import (
    CRITEO_NO_ADVERTISERS_ERROR,
    CriteoResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.settings import (
    CRITEO_API_VERSION,
    CRITEO_ENDPOINTS,
    ENDPOINTS,
    STATS_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.source import CriteoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.criteo import CriteoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.criteo.source"


def _inputs(schema_name: str, **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestCriteoSource:
    def setup_method(self) -> None:
        self.source = CriteoSource()
        self.team_id = 123
        self.config = CriteoSourceConfig(client_id="client-id", client_secret="client-secret")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CRITEO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Criteo"
        assert config.label == "Criteo"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/criteo.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["client_id", "client_secret", "report_currency", "report_timezone"]

    def test_client_secret_is_the_only_secret_field(self) -> None:
        config = self.source.get_source_config
        input_fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]

        secret_fields = [f for f in input_fields if f.secret]
        assert [f.name for f in secret_fields] == ["client_secret"]
        assert secret_fields[0].type == SourceFieldInputConfigType.PASSWORD

    def test_report_fields_are_optional(self) -> None:
        config = self.source.get_source_config
        optional = {
            f.name: f.required
            for f in config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name.startswith("report_")
        }
        # Both fall back to Criteo's own defaults (USD / UTC) when left blank.
        assert optional == {"report_currency": False, "report_timezone": False}

    def test_api_version_metadata_pins_the_version_the_paths_use(self) -> None:
        assert self.source.supported_versions == (CRITEO_API_VERSION,)
        assert self.source.default_version == CRITEO_API_VERSION
        assert self.source.api_docs_url.startswith("https://")

    def test_lists_tables_without_credentials(self) -> None:
        # `get_schemas` walks a static catalog, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            f"HTTP 401 from the OAuth2 token endpoint: invalid_client {OAUTH2_PERMANENT_ERROR_MARKER}",
            f"HTTP 400 from the OAuth2 token endpoint {OAUTH2_PERMANENT_ERROR_MARKER}",
            "403 Client Error: Forbidden for url: https://api.criteo.com/2026-01/marketing-solutions/ads",
            CRITEO_NO_ADVERTISERS_ERROR,
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "403 Client Error: Forbidden for url: https://api.stripe.com/v1/charges",
            "500 Server Error for url: https://api.criteo.com/2026-01/statistics/report",
            # A transient token error shares the endpoint phrasing but carries no permanent marker.
            "HTTP 503 from the OAuth2 token endpoint",
            # A mid-sync 401 is re-minted, not a disable condition.
            "401 Client Error: Unauthorized for url: https://api.criteo.com/2026-01/advertisers/me",
        ],
    )
    def test_non_retryable_errors_ignore_transient_and_unrelated(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert [s.name for s in schemas] == list(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", [name for name in ENDPOINTS if name != "campaign_stats"])
    def test_entity_endpoints_are_full_refresh(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        # None of the entity endpoints expose a server-side updated-since filter.
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_campaign_stats_is_incremental_merge_only_with_lookback(self) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == "campaign_stats")

        assert schema.supports_incremental is True
        # Appending restated days would double-count them; the report table has to merge.
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == ["Day"]
        assert schema.default_incremental_lookback_seconds == STATS_LOOKBACK_SECONDS

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["campaigns", "campaign_stats"])
        assert [s.name for s in schemas] == ["campaigns", "campaign_stats"]

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
        for name, entry in descriptions.items():
            assert entry["description"]
            assert entry["docs_url"].startswith("https://")
            # Every declared primary-key column must be documented, since those are the columns a
            # consumer joins on.
            assert set(CRITEO_ENDPOINTS[name].primary_key) <= set(entry["columns"])

    @pytest.mark.parametrize(
        "returned, expected",
        [
            ((True, None), (True, None)),
            ((False, CRITEO_NO_ADVERTISERS_ERROR), (False, CRITEO_NO_ADVERTISERS_ERROR)),
        ],
    )
    def test_validate_credentials_passes_through_transport_result(
        self, returned: tuple[bool, Optional[str]], expected: tuple[bool, Optional[str]]
    ) -> None:
        with mock.patch(f"{_SOURCE_MODULE}.validate_criteo_credentials", return_value=returned) as validate:
            assert self.source.validate_credentials(self.config, self.team_id) == expected

        validate.assert_called_once_with("client-id", "client-secret", CRITEO_API_VERSION)

    def test_validate_credentials_honors_a_pinned_api_version(self) -> None:
        with mock.patch(f"{_SOURCE_MODULE}.validate_criteo_credentials", return_value=(True, None)) as validate:
            self.source.validate_credentials(self.config, self.team_id, api_version="2025-10")

        assert validate.call_args.args[2] == "2025-10"

    def test_resumable_manager_is_bound_to_the_resume_class_and_namespaced_per_schema(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs("ads"))
        other = self.source.get_resumable_source_manager(_inputs("audiences"))

        assert manager._data_class is CriteoResumeConfig
        # Endpoints store incompatible cursors, so their Redis slots must not collide.
        assert manager._key != other._key
        assert manager._key.endswith(":ads")

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_declares_the_endpoint_primary_keys(self, endpoint: str) -> None:
        response = self.source.source_for_pipeline(
            self.config, self.source.get_resumable_source_manager(_inputs(endpoint)), _inputs(endpoint)
        )

        assert response.name == endpoint
        assert response.primary_keys == CRITEO_ENDPOINTS[endpoint].primary_key
        assert response.sort_mode == "asc"

    def test_source_for_pipeline_plumbs_the_incremental_watermark(self) -> None:
        module = "products.warehouse_sources.backend.temporal.data_imports.sources.criteo.source.criteo_source"
        inputs = _inputs(
            "campaign_stats",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-05",
            api_version=CRITEO_API_VERSION,
        )
        manager = self.source.get_resumable_source_manager(inputs)

        with mock.patch(module) as criteo_source:
            self.source.source_for_pipeline(
                CriteoSourceConfig(
                    client_id="client-id",
                    client_secret="client-secret",
                    report_currency="EUR",
                    report_timezone="Europe/Paris",
                ),
                manager,
                inputs,
            )

        kwargs = criteo_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] == "2026-01-05"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["report_currency"] == "EUR"
        assert kwargs["report_timezone"] == "Europe/Paris"
        assert kwargs["api_version"] == CRITEO_API_VERSION

    def test_source_for_pipeline_withholds_the_watermark_on_a_full_refresh(self) -> None:
        module = "products.warehouse_sources.backend.temporal.data_imports.sources.criteo.source.criteo_source"
        inputs = _inputs(
            "campaign_stats", should_use_incremental_field=False, db_incremental_field_last_value="2026-01-05"
        )

        with mock.patch(module) as criteo_source:
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)

        assert criteo_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @pytest.mark.parametrize(
        "endpoint, expected_partition_key",
        [
            ("advertisers", None),
            ("campaigns", None),
            ("audiences", "createdAt"),
            ("campaign_stats", "Day"),
        ],
    )
    def test_partitioning_uses_stable_keys_only(self, endpoint: str, expected_partition_key: Optional[str]) -> None:
        response = self.source.source_for_pipeline(
            self.config, self.source.get_resumable_source_manager(_inputs(endpoint)), _inputs(endpoint)
        )

        if expected_partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [expected_partition_key]

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = cast("Iterable[dict[str, Any]]", self.source.get_documented_tables())
        assert {table["name"] for table in tables} == set(ENDPOINTS)
