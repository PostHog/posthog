from typing import Any, Optional

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.loopreturns import (
    LoopReturnsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns import (
    LoopReturnsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.source import LoopReturnsSource

VALIDATE_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.source."
    "validate_loop_returns_credentials"
)


class FakeResumableSourceManager(ResumableSourceManager[LoopReturnsResumeConfig]):
    def __init__(self) -> None:
        pass

    def can_resume(self) -> bool:
        return False

    def load_state(self) -> Optional[LoopReturnsResumeConfig]:
        return None


def _source_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "returns",
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
    return SourceInputs(**{**defaults, **overrides})


class TestLoopReturnsSource:
    def setup_method(self) -> None:
        self.source = LoopReturnsSource()
        self.team_id = 1
        self.config = LoopReturnsSourceConfig(api_key="loop_test_key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.label == "Loop Returns"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/loop_returns.png"

        fields = {field.name: field for field in config.fields if isinstance(field, SourceFieldInputConfig)}
        assert set(fields) == {"api_key", "start_date"}
        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True
        # The start date only bounds a backfill, so requiring it would block setup for no reason.
        assert fields["start_date"].required is False

    def test_get_schemas(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only the endpoints with a server-side `from`/`to` filter may claim incremental support.
        assert {name for name, schema in schemas.items() if schema.supports_incremental} == set(INCREMENTAL_FIELDS)
        assert [field["field"] for field in schemas["returns"].incremental_fields] == ["created_at", "updated_at"]
        assert [field["field"] for field in schemas["advanced_shipping_notices"].incremental_fields] == ["created_at"]

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_every_endpoint_is_documented(self, endpoint: str) -> None:
        # `lists_tables_without_credentials` publishes this catalog to the public docs, so an
        # endpoint added without a canonical entry ships an undocumented table.
        entry = self.source.get_canonical_descriptions()[endpoint]

        assert entry["description"]
        assert entry["docs_url"].startswith("https://docs.loopreturns.com/")
        assert entry["columns"]["id"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.loopreturns.com/api/v1/warehouse/return/list",
            "403 Client Error: Forbidden for url: https://api.loopreturns.com/api/v1/destinations",
        ],
    )
    def test_auth_failures_are_non_retryable(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_other_vendors_auth_failures_are_left_alone(self) -> None:
        assert not any(
            key in "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers"
            for key in self.source.get_non_retryable_errors()
        )

    @pytest.mark.parametrize(
        ("pinned", "expected_version"),
        [
            # No pin resolves to the default (the current GA date version), a `v1` pin is honored
            # verbatim so a customer still on the alias keeps hitting `/api/v1`, and an explicit
            # `2026-07` pin passes straight through. A broken dispatch would move a pinned source.
            (None, "2026-07"),
            ("v1", "v1"),
            ("2026-07", "2026-07"),
        ],
    )
    @mock.patch(VALIDATE_PATH)
    def test_validate_credentials_threads_the_resolved_version(
        self, mock_validate: mock.MagicMock, pinned: Optional[str], expected_version: str
    ) -> None:
        mock_validate.return_value = (True, None)

        assert self.source.validate_credentials(
            self.config, self.team_id, schema_name="destinations", api_version=pinned
        ) == (True, None)
        mock_validate.assert_called_once_with("loop_test_key", expected_version, schema_name="destinations")

    def test_v1_is_deprecated_without_a_sunset_date(self) -> None:
        # Loop publishes no calendar sunset for the alias, so the pin stays fully supported; the
        # metadata only lights up the generic in-product deprecation warning.
        deprecation = self.source.get_version_deprecation("v1")

        assert deprecation is not None
        assert deprecation.sunset_at is None
        assert self.source.get_version_deprecation("2026-07") is None

    @pytest.mark.parametrize("start_date", ["not-a-date", "2024-13-01", "1000-01-01"])
    @mock.patch(VALIDATE_PATH)
    def test_a_bad_start_date_is_rejected_before_calling_loop(
        self, mock_validate: mock.MagicMock, start_date: str
    ) -> None:
        config = LoopReturnsSourceConfig(api_key="loop_test_key", start_date=start_date)

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error is not None and "Start date" in error
        mock_validate.assert_not_called()

    @mock.patch(VALIDATE_PATH)
    def test_a_valid_start_date_is_accepted(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        config = LoopReturnsSourceConfig(api_key="loop_test_key", start_date="2024-01-01")

        assert self.source.validate_credentials(config, self.team_id) == (True, None)

    def test_source_for_pipeline_builds_the_requested_table(self) -> None:
        source_response = self.source.source_for_pipeline(
            self.config, FakeResumableSourceManager(), _source_inputs(schema_name="advanced_shipping_notices")
        )

        assert source_response.name == "advanced_shipping_notices"
        assert source_response.primary_keys == ["id", "return_line_item_id"]

    def test_source_for_pipeline_ignores_a_stale_watermark_on_a_full_refresh(self) -> None:
        source_response = self.source.source_for_pipeline(
            self.config,
            FakeResumableSourceManager(),
            _source_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2025-01-01T00:00:00Z"),
        )

        assert source_response.sort_mode == "asc"
