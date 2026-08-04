from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.worldbank import (
    WorldBankSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.settings import ENDPOINTS, PRIMARY_KEYS
from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.source import WorldBankSource
from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.world_bank import WorldBankResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(schema_name: str = "countries") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestWorldBankSource:
    def setup_method(self) -> None:
        self.source = WorldBankSource()
        self.config = WorldBankSourceConfig(indicator_codes="SP.POP.TOTL\nNY.GDP.PCAP.CD")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.WORLDBANK

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "WorldBank"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/world-bank"
        assert config.iconPath == "/static/services/world_bank.png"
        # A finished source ships visible; re-adding the flag would hide it from every user.
        assert not config.unreleasedSource

    def test_get_source_config_fields(self) -> None:
        fields = [field for field in self.source.get_source_config.fields if isinstance(field, SourceFieldInputConfig)]

        assert [field.name for field in fields] == ["indicator_codes"]
        assert fields[0].type == SourceFieldInputConfigType.TEXTAREA
        assert fields[0].required is True
        # The API is open, so nothing on this form is a credential.
        assert fields[0].secret is False

    def test_pinned_version_matches_the_path_the_code_calls(self) -> None:
        assert self.source.default_version == "v2"
        assert self.source.supported_versions == ("v2",)
        assert self.source.resolve_api_version(None) == "v2"

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=123)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        # No endpoint has a server-side "changed since" filter, so nothing may advertise
        # incremental or append sync.
        assert not any(schema.supports_incremental for schema in schemas)
        assert not any(schema.supports_append for schema in schemas)
        assert all(schema.description for schema in schemas)

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=123, names=["indicator_data"])

        assert [schema.name for schema in schemas] == ["indicator_data"]

    def test_documented_tables_render_without_credentials(self) -> None:
        # The public docs endpoint builds a blank config and calls get_schemas, so discovery must
        # do no I/O.
        tables = self.source.get_documented_tables()

        assert [table["name"] for table in tables] == list(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_every_endpoint_has_a_primary_key_and_canonical_descriptions(self, endpoint: str) -> None:
        assert PRIMARY_KEYS[endpoint]
        assert CANONICAL_DESCRIPTIONS[endpoint]["columns"]

    def test_indicator_data_primary_key_is_unique_table_wide(self) -> None:
        # One table holds observations for every configured indicator, so the indicator has to be
        # part of the key or codes would overwrite each other.
        assert PRIMARY_KEYS["indicator_data"] == ["indicator_id", "country_id", "date"]

    def test_get_resumable_source_manager_is_bound_to_the_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WorldBankResumeConfig

    def test_non_retryable_error_matches_the_required_selector_failure(self) -> None:
        raised = "Required data_selector '[1]' matched nothing in the response (body keys: list). ..."

        assert error_message_matches(raised, self.source.get_non_retryable_errors().keys())

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_source_for_pipeline_plumbs_the_endpoint_through(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.source.world_bank_source"
        ) as mock_source:
            mock_source.return_value = iter([])
            response = self.source.source_for_pipeline(self.config, manager, _make_inputs(endpoint))
            list(cast(Iterable[Any], response.items()))

        assert response.name == endpoint
        assert response.primary_keys == PRIMARY_KEYS[endpoint]
        assert mock_source.call_args.kwargs["endpoint"] == endpoint
        assert mock_source.call_args.kwargs["indicator_codes"] == ["SP.POP.TOTL", "NY.GDP.PCAP.CD"]
        assert mock_source.call_args.kwargs["api_version"] == "v2"

    @pytest.mark.parametrize(
        ("indicator_codes", "expected_codes"),
        [
            ("SP.POP.TOTL", ["SP.POP.TOTL"]),
            ("", []),
        ],
    )
    def test_validate_credentials_parses_the_codes_before_probing(
        self, indicator_codes: str, expected_codes: list[str]
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.source.validate_world_bank_credentials"
        ) as mock_validate:
            mock_validate.return_value = (True, None)
            self.source.validate_credentials(WorldBankSourceConfig(indicator_codes=indicator_codes), team_id=123)

        assert mock_validate.call_args.args == (expected_codes, "v2")
