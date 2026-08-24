import datetime
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import structlog
from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.whogho import WhoGhoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.settings import ENDPOINTS, PRIMARY_KEYS
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.source import WhoGhoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.who_gho import (
    MAX_INDICATOR_CODES,
    WhoGhoResumeConfig,
    who_gho_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(
    schema_name: str = "indicators",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="Date" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestWhoGhoSource:
    def setup_method(self) -> None:
        self.source = WhoGhoSource()
        self.config = WhoGhoSourceConfig(indicator_codes="WHOSIS_000001\nWHOSIS_000002")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.WHOGHO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "WhoGho"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/who-gho"
        assert config.iconPath == "/static/services/who_gho.png"
        # A finished source ships visible; re-adding the flag would hide it from every user.
        assert not config.unreleasedSource

    def test_get_source_config_fields(self) -> None:
        fields = [field for field in self.source.get_source_config.fields if isinstance(field, SourceFieldInputConfig)]

        assert [field.name for field in fields] == ["indicator_codes"]
        assert fields[0].type == SourceFieldInputConfigType.TEXTAREA
        assert fields[0].required is True
        # The API is open, so nothing on this form is a credential.
        assert fields[0].secret is False

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=123)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        assert all(schema.description for schema in schemas)

    def test_only_indicator_data_supports_incremental(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, team_id=123)}

        assert schemas["indicator_data"].supports_incremental
        assert not schemas["indicators"].supports_incremental
        assert not schemas["dimensions"].supports_incremental
        assert not schemas["dimension_values"].supports_incremental

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=123, names=["indicator_data"])

        assert [schema.name for schema in schemas] == ["indicator_data"]

    def test_documented_tables_render_without_credentials(self) -> None:
        # The public docs endpoint builds a blank config and calls get_schemas, so discovery must
        # do no I/O.
        tables = self.source.get_documented_tables()

        assert [table["name"] for table in tables] == list(ENDPOINTS)

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_every_endpoint_has_a_primary_key_and_canonical_descriptions(self, endpoint: str) -> None:
        assert PRIMARY_KEYS[endpoint]
        assert CANONICAL_DESCRIPTIONS[endpoint]["columns"]

    def test_indicator_data_primary_key_includes_the_indicator_code(self) -> None:
        # One table holds observations for every configured indicator, and each indicator has its
        # own Id sequence (a separate OData entity type per code), so the code has to be part of
        # the key or two indicators could overwrite each other's rows.
        assert PRIMARY_KEYS["indicator_data"] == ["IndicatorCode", "Id"]

    def test_dimension_values_primary_key_is_just_code(self) -> None:
        # Unlike indicator_data, every dimension shares one DIMENSION_VALUE entity type, and the
        # API declares Code as that entity's only key -- it is genuinely unique table-wide.
        assert PRIMARY_KEYS["dimension_values"] == ["Code"]

    def test_get_resumable_source_manager_is_bound_to_the_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WhoGhoResumeConfig

    def test_non_retryable_error_matches_an_unknown_indicator_code(self) -> None:
        raised = "404 Client Error: Not Found for url: https://ghoapi.azureedge.net/api/NOT_REAL"

        assert error_message_matches(raised, self.source.get_non_retryable_errors().keys())

    def test_non_retryable_error_matches_an_out_of_bounds_code_list(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            list(
                who_gho_source(
                    endpoint="indicator_data",
                    indicator_codes=[f"CODE.{index}" for index in range(MAX_INDICATOR_CODES + 1)],
                    team_id=123,
                    job_id="job-id",
                    resumable_source_manager=MagicMock(spec=ResumableSourceManager),
                )
            )

        assert error_message_matches(str(excinfo.value), self.source.get_non_retryable_errors().keys())

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_for_pipeline_plumbs_the_endpoint_through(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.source.who_gho_source"
        ) as mock_source:
            mock_source.return_value = iter([])
            response = self.source.source_for_pipeline(self.config, manager, _make_inputs(endpoint))
            list(cast(Iterable[Any], response.items()))

        assert response.name == endpoint
        assert response.primary_keys == PRIMARY_KEYS[endpoint]
        assert mock_source.call_args.kwargs["endpoint"] == endpoint
        assert mock_source.call_args.kwargs["indicator_codes"] == ["WHOSIS_000001", "WHOSIS_000002"]

    def test_source_for_pipeline_formats_the_incremental_watermark_as_a_plain_date(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs(
            "indicator_data",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.datetime(2024, 8, 2, 9, 43, 39),
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.source.who_gho_source"
        ) as mock_source:
            mock_source.return_value = iter([])
            response = self.source.source_for_pipeline(self.config, manager, inputs)
            list(cast(Iterable[Any], response.items()))

        assert mock_source.call_args.kwargs["since"] == "2024-08-02"
        assert mock_source.call_args.kwargs["should_use_incremental_field"] is True

    def test_source_for_pipeline_omits_since_on_a_full_sync(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs("indicator_data", should_use_incremental_field=False)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.source.who_gho_source"
        ) as mock_source:
            mock_source.return_value = iter([])
            response = self.source.source_for_pipeline(self.config, manager, inputs)
            list(cast(Iterable[Any], response.items()))

        assert mock_source.call_args.kwargs["since"] is None

    @parameterized.expand(
        [
            ("WHOSIS_000001", ["WHOSIS_000001"]),
            ("", []),
        ]
    )
    def test_validate_credentials_parses_the_codes_before_probing(
        self, indicator_codes: str, expected_codes: list[str]
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.source.validate_who_gho_credentials"
        ) as mock_validate:
            mock_validate.return_value = (True, None)
            self.source.validate_credentials(WhoGhoSourceConfig(indicator_codes=indicator_codes), team_id=123)

        assert mock_validate.call_args.args == (expected_codes,)
