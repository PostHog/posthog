from typing import Any, cast

from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.similarweb import (
    SimilarwebSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.settings import (
    ENDPOINTS,
    MAX_DOMAINS,
    SIMILARWEB_ENDPOINTS,
    TRAFFIC_BY_COUNTRY,
    VISITS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.similarweb import (
    SimilarwebResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.source import SimilarwebSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.source"


def _inputs(schema_name: str = VISITS, **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    return SourceInputs(**{**defaults, **overrides})


class TestSimilarwebSource:
    def setup_method(self) -> None:
        self.source = SimilarwebSource()
        self.team_id = 123
        self.config = SimilarwebSourceConfig(api_key="key-123", domains="posthog.com")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SIMILARWEB

    def test_get_source_config_is_released(self) -> None:
        config = self.source.get_source_config

        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.name.value == "Similarweb"
        assert config.iconPath == "/static/services/similarweb.png"

        fields_by_name = {field.name: field for field in config.fields}
        assert set(fields_by_name) == {"api_key", "domains", "country", "granularity", "start_date"}

        api_key = fields_by_name["api_key"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.required is True
        assert api_key.secret is True
        assert api_key.type == SourceFieldInputConfigType.PASSWORD

        assert cast(SourceFieldInputConfig, fields_by_name["domains"]).required is True
        assert cast(SourceFieldInputConfig, fields_by_name["country"]).required is False
        assert cast(SourceFieldInputConfig, fields_by_name["start_date"]).required is False

        granularity = fields_by_name["granularity"]
        assert isinstance(granularity, SourceFieldSelectConfig)
        assert granularity.defaultValue == "monthly"
        assert [option.value for option in granularity.options] == ["monthly", "weekly", "daily"]

    def test_get_schemas_covers_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        by_name = {schema.name: schema for schema in schemas}
        for name, endpoint in SIMILARWEB_ENDPOINTS.items():
            assert by_name[name].description == endpoint.description
            # The geo breakdown aggregates the whole window into rows with no period column,
            # so it must not advertise a cursor the pipeline would try to advance.
            assert by_name[name].supports_incremental is (name != TRAFFIC_BY_COUNTRY)
            if name != TRAFFIC_BY_COUNTRY:
                assert {field["field"] for field in by_name[name].incremental_fields} == {"date"}

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=[VISITS])
        assert [schema.name for schema in schemas] == [VISITS]

    @parameterized.expand(
        [
            ("no_domains", {"domains": " "}, "Add at least one domain"),
            (
                "too_many_domains",
                {"domains": ",".join(f"d{i}.com" for i in range(MAX_DOMAINS + 1))},
                "Too many domains",
            ),
            ("bad_country", {"country": "usa"}, "two-letter code"),
            ("bad_start_month", {"start_date": "01-2024"}, "YYYY-MM format"),
        ]
    )
    def test_validate_credentials_rejects_bad_settings_without_calling_the_api(
        self, _name: str, overrides: dict[str, Any], expected: str
    ) -> None:
        config = SimilarwebSourceConfig(**{"api_key": "key-123", "domains": "posthog.com", **overrides})

        with mock.patch(f"{MODULE}.validate_similarweb_credentials") as probe:
            is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message is not None and expected in message
        probe.assert_not_called()

    def test_validate_credentials_probes_the_api_when_settings_are_valid(self) -> None:
        with mock.patch(f"{MODULE}.validate_similarweb_credentials", return_value=(True, None)) as probe:
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        probe.assert_called_once_with("key-123")

    def test_get_resumable_source_manager_is_bound_to_the_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SimilarwebResumeConfig

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_primary_keys_identify_a_row_across_domains(self, name: str) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        response = self.source.source_for_pipeline(self.config, manager, _inputs(schema_name=name))

        endpoint = SIMILARWEB_ENDPOINTS[name]
        assert response.name == name
        assert response.primary_keys == endpoint.primary_keys
        # Every table pools rows from every configured domain, so a key without the domain
        # would collapse different domains' rows onto each other on merge.
        assert response.primary_keys is not None and "domain" in response.primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_keys == ([endpoint.partition_key] if endpoint.partition_key else None)

    def test_source_for_pipeline_drops_the_watermark_on_a_full_refresh(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _inputs(should_use_incremental_field=False, db_incremental_field_last_value="2024-04")

        with mock.patch(f"{MODULE}.similarweb_source") as build:
            self.source.source_for_pipeline(self.config, manager, inputs)

        assert build.call_args.kwargs["db_incremental_field_last_value"] is None
        assert build.call_args.kwargs["api_key"] == "key-123"
        assert build.call_args.kwargs["domains"] == "posthog.com"
        assert build.call_args.kwargs["granularity"] == "monthly"

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() == CANONICAL_DESCRIPTIONS
