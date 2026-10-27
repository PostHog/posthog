from typing import Optional

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openalex import (
    OpenalexSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.source import OpenalexSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.openalex.source"


class TestOpenalexSource:
    def setup_method(self) -> None:
        self.source = OpenalexSource()
        self.config = OpenalexSourceConfig(api_key="key")

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_only_works_and_locations_advertise_incremental_sync(self, endpoint: str) -> None:
        # OpenAlex gates its updated/created date filters behind a paid plan, so only the free
        # `publication_date` and `ingested_at` filters give a usable server-side timestamp filter.
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)
        expected_fields = {"works": ["publication_date"], "locations": ["ingested_at"]}

        if endpoint in expected_fields:
            assert schema.supports_incremental is True
            assert [f["field"] for f in schema.incremental_fields] == expected_fields[endpoint]
        else:
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_incremental_fields_only_cover_known_endpoints(self) -> None:
        assert set(INCREMENTAL_FIELDS) <= set(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://api.openalex.org/works?per_page=200",
        ],
    )
    def test_auth_and_plan_failures_are_non_retryable(self, observed_error: str) -> None:
        assert any(prefix in observed_error for prefix in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "endpoint,expected_filter",
        [
            ("works", "works-scope"),
            ("authors", "authors-scope"),
            ("awards", "awards-scope"),
            ("locations", "locations-scope"),
            ("topics", None),
            ("institutions", None),
        ],
    )
    def test_each_table_gets_its_own_filter(self, endpoint: str, expected_filter: Optional[str]) -> None:
        # Sending the works filter to another entity would be rejected as an invalid filter field.
        config = OpenalexSourceConfig(
            api_key="key",
            works_filter="works-scope",
            authors_filter="authors-scope",
            awards_filter="awards-scope",
            locations_filter="locations-scope",
        )

        result = SourceDriver(self.source, config).run(
            endpoint,
            [ScriptedResponse(json={"meta": {"count": 1, "next_cursor": None}, "results": [{"id": "W1"}]})],
        )

        assert result.raised is None
        assert result.paths == [f"/{endpoint}"]
        assert result.requests[0].param("filter") == expected_filter

    @patch(f"{SOURCE_MODULE}.validate_openalex_credentials")
    def test_validate_credentials_probes_every_configured_filter(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (True, None)
        config = OpenalexSourceConfig(api_key="key", works_filter="works-scope", awards_filter="awards-scope")

        assert self.source.validate_credentials(config, team_id=1) == (True, None)

        assert mock_validate.call_args.args[0] == "key"
        assert mock_validate.call_args.args[1] == {
            "works": "works-scope",
            "authors": None,
            "awards": "awards-scope",
            "locations": None,
        }
