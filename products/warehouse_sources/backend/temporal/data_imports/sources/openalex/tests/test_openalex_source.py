from typing import Optional

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openalex import (
    OpenalexSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.openalex import OpenAlexResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.source import OpenalexSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.openalex.source"


def _inputs(schema_name: str) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestOpenalexSource:
    def setup_method(self) -> None:
        self.source = OpenalexSource()
        self.config = OpenalexSourceConfig(api_key="key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.OPENALEX

    def test_source_ships_visible_in_alpha(self) -> None:
        config = self.source.get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.label == "OpenAlex"
        assert config.iconPath == "/static/services/openalex.png"

    def test_fields(self) -> None:
        fields = [f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldInputConfig)]

        assert [f.name for f in fields] == ["api_key", "works_filter", "authors_filter", "awards_filter"]

        api_key = fields[0]
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True
        assert all(f.required is False and f.secret is False for f in fields[1:])

    def test_get_schemas_lists_every_endpoint_without_credentials(self) -> None:
        schemas = self.source.get_schemas(OpenalexSourceConfig(api_key=""), team_id=1)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["works", "topics"])

        assert {schema.name for schema in schemas} == {"works", "topics"}

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_only_works_advertises_incremental_sync(self, endpoint: str) -> None:
        # OpenAlex gates its updated/created date filters behind a paid plan, so `works` is the
        # only table with a usable server-side timestamp filter.
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)

        if endpoint == "works":
            assert schema.supports_incremental is True
            assert [f["field"] for f in schema.incremental_fields] == ["publication_date"]
        else:
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_incremental_fields_only_cover_known_endpoints(self) -> None:
        assert set(INCREMENTAL_FIELDS) <= set(ENDPOINTS)

    def test_canonical_descriptions_are_keyed_by_schema_name(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert descriptions is CANONICAL_DESCRIPTIONS
        assert set(descriptions) <= set(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.openalex.org/works?per_page=200",
            "403 Client Error: Forbidden for url: https://api.openalex.org/works?per_page=200",
            "400 Client Error: Bad Request for url: https://api.openalex.org/works?per_page=200",
        ],
    )
    def test_auth_and_plan_failures_are_non_retryable(self, observed_error: str) -> None:
        assert any(prefix in observed_error for prefix in self.source.get_non_retryable_errors())

    def test_resumable_manager_is_bound_to_the_cursor_dataclass(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs("works"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OpenAlexResumeConfig

    @pytest.mark.parametrize(
        "endpoint,expected_filter",
        [
            ("works", "works-scope"),
            ("authors", "authors-scope"),
            ("awards", "awards-scope"),
            ("topics", None),
            ("institutions", None),
        ],
    )
    @patch(f"{SOURCE_MODULE}.openalex_source")
    def test_each_table_gets_its_own_filter(
        self, mock_openalex_source: MagicMock, endpoint: str, expected_filter: Optional[str]
    ) -> None:
        # Sending the works filter to another entity would be rejected as an invalid filter field.
        config = OpenalexSourceConfig(
            api_key="key",
            works_filter="works-scope",
            authors_filter="authors-scope",
            awards_filter="awards-scope",
        )

        self.source.source_for_pipeline(config, MagicMock(spec=ResumableSourceManager), _inputs(endpoint))

        assert mock_openalex_source.call_args.kwargs["entity_filter"] == expected_filter
        assert mock_openalex_source.call_args.kwargs["endpoint"] == endpoint

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
        }
