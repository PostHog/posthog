from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.beehiiv import BeehiivResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.source import BeehiivSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.beehiiv import (
    BeehiivSourceConfig,
)

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.source.validate_beehiiv_credentials"
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
        with patch(VALIDATE_PATCH) as mock_validate:
            is_valid, error = self.source.validate_credentials(_config(publication_id), team_id=7)

        assert is_valid is False
        assert error == expected_error
        mock_validate.assert_not_called()

    @pytest.mark.parametrize(
        ("schema_name", "expected_allow_missing_scope"),
        [(None, True), ("Subscriptions", False)],
    )
    def test_missing_scope_is_only_tolerated_at_source_create(
        self, schema_name: str | None, expected_allow_missing_scope: bool
    ) -> None:
        with patch(VALIDATE_PATCH, return_value=(True, None)) as mock_validate:
            self.source.validate_credentials(_config(), team_id=7, schema_name=schema_name)

        assert mock_validate.call_args.kwargs["allow_missing_scope"] is expected_allow_missing_scope

    def test_publication_id_is_trimmed_before_use(self) -> None:
        with patch(VALIDATE_PATCH, return_value=(True, None)) as mock_validate:
            self.source.validate_credentials(_config("  pub_123  "), team_id=7)

        assert mock_validate.call_args.kwargs["publication_id"] == "pub_123"

    def test_falls_back_to_the_default_api_version(self) -> None:
        with patch(VALIDATE_PATCH, return_value=(True, None)) as mock_validate:
            self.source.validate_credentials(_config(), team_id=7, api_version=None)

        assert mock_validate.call_args.kwargs["api_version"] == "v2"


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
