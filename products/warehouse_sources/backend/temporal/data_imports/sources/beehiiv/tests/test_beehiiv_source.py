from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.beehiiv import BeehiivResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.source import BeehiivSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.beehiiv import (
    BeehiivSourceConfig,
)


def _config(publication_id: str = "pub_123") -> BeehiivSourceConfig:
    return BeehiivSourceConfig(api_key="test-key", publication_id=publication_id)


def _source_inputs(schema_name: str = "Subscriptions") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=7,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestBeehiivSource:
    def setup_method(self) -> None:
        self.source = BeehiivSource()

    @pytest.mark.parametrize(
        "endpoint", sorted(name for name, config in ENDPOINTS.items() if config.partition_key is not None)
    )
    def test_partition_key_is_a_documented_column(self, endpoint: str) -> None:
        # Partitioning on a column beehiiv does not return silently produces one null
        # partition for the whole table.
        partition_key = ENDPOINTS[endpoint].partition_key
        columns: dict[str, Any] = CANONICAL_DESCRIPTIONS[endpoint].get("columns") or {}

        assert partition_key in columns


class TestBeehiivValidateCredentialsWiring:
    def setup_method(self) -> None:
        self.source = BeehiivSource()

    @pytest.mark.parametrize(
        ("publication_id", "expected_error"),
        [
            ("", "Publication ID is required."),
            ("   ", "Publication ID is required."),
            (
                "pub_1/webhooks",
                "Publication ID must be a single value with no slashes, for example pub_00000000-0000-0000-0000-000000000000.",
            ),
            (
                "../publications",
                "Publication ID must be a single value with no slashes, for example pub_00000000-0000-0000-0000-000000000000.",
            ),
        ],
    )
    def test_rejects_publication_ids_that_are_not_a_single_path_segment(
        self, publication_id: str, expected_error: str
    ) -> None:
        with scripted_network([]) as network:
            is_valid, error = self.source.validate_credentials(_config(publication_id), team_id=7)

        assert is_valid is False
        assert error == expected_error
        assert network.requests_log == []

    @pytest.mark.parametrize(
        ("schema_name", "expected_allow_missing_scope"),
        [(None, True), ("Subscriptions", False)],
    )
    def test_missing_scope_is_only_tolerated_at_source_create(
        self, schema_name: str | None, expected_allow_missing_scope: bool
    ) -> None:
        with scripted_network([ScriptedResponse(status=403)]) as network:
            is_valid, error = self.source.validate_credentials(_config(), team_id=7, schema_name=schema_name)

        assert is_valid is expected_allow_missing_scope
        assert (error is None) is expected_allow_missing_scope
        assert [request.path for request in network.requests_log] == ["/v2/publications/pub_123"]

    def test_publication_id_is_trimmed_before_use(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            is_valid, error = self.source.validate_credentials(_config("  pub_123  "), team_id=7)

        assert (is_valid, error) == (True, None)
        assert [request.path for request in network.requests_log] == ["/v2/publications/pub_123"]

    def test_falls_back_to_the_default_api_version(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            is_valid, error = self.source.validate_credentials(_config(), team_id=7, api_version=None)

        assert (is_valid, error) == (True, None)
        assert [request.path for request in network.requests_log] == ["/v2/publications/pub_123"]


class TestBeehiivPipelineDispatch:
    def setup_method(self) -> None:
        self.source = BeehiivSource()

    def test_resume_state_is_namespaced_per_table(self) -> None:
        # Cursor and page endpoints persist incompatible paginator snapshots; sharing one
        # Redis slot would replay a cursor against a paged endpoint.
        subscriptions = self.source.get_resumable_source_manager(_source_inputs("Subscriptions"))
        posts = self.source.get_resumable_source_manager(_source_inputs("Posts"))

        assert subscriptions._data_class is BeehiivResumeConfig
        assert subscriptions._key != posts._key
        assert subscriptions._key.endswith(":Subscriptions")

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_source_response_matches_the_endpoint_catalog(self, endpoint: str) -> None:
        endpoint_config = ENDPOINTS[endpoint]
        result = SourceDriver(self.source, _config()).run(
            endpoint,
            [ScriptedResponse(json={"data": [], "total_pages": 1, "has_more": False, "next_cursor": None})],
        )

        assert result.raised is None
        assert result.response is not None
        response = result.response
        assert response.name == endpoint
        assert response.primary_keys == [endpoint_config.primary_key]
        assert response.sort_mode == endpoint_config.sort_mode
        if endpoint_config.partition_key is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [endpoint_config.partition_key]
            assert response.partition_mode == "datetime"
