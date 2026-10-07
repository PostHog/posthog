from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import structlog
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nagerdate import (
    NagerDateSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.settings import ENDPOINTS, PRIMARY_KEYS
from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.source import NagerDateSource


def _make_inputs(schema_name: str = "Countries") -> SourceInputs:
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


class TestNagerDateSource:
    def setup_method(self) -> None:
        self.source = NagerDateSource()
        self.config = NagerDateSourceConfig(country_codes="US\nGB")

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_every_endpoint_has_a_primary_key_and_canonical_descriptions(self, endpoint: str) -> None:
        assert PRIMARY_KEYS[endpoint]
        assert CANONICAL_DESCRIPTIONS[endpoint]["columns"]

    @parameterized.expand([("PublicHolidays",), ("NextPublicHolidays",)])
    def test_holiday_tables_key_on_the_synthetic_id(self, endpoint: str) -> None:
        # (countryCode, date, name) alone isn't unique: the same holiday can be split across
        # subdivisions with different classifications, so these tables key on the synthetic id
        # this source adds rather than the raw API fields.
        assert PRIMARY_KEYS[endpoint] == ["id"]

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_source_for_pipeline_plumbs_the_endpoint_through(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.source.nager_date_source"
        ) as mock_source:
            mock_source.return_value = iter([])
            response = self.source.source_for_pipeline(self.config, manager, _make_inputs(endpoint))
            list(cast(Iterable[Any], response.items()))

        assert response.name == endpoint
        assert response.primary_keys == PRIMARY_KEYS[endpoint]
        assert mock_source.call_args.kwargs["endpoint"] == endpoint
        assert mock_source.call_args.kwargs["country_codes"] == ["US", "GB"]
