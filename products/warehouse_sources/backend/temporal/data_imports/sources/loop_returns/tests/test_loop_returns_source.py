from typing import Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.loopreturns import (
    LoopReturnsSourceConfig,
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


class TestLoopReturnsSource:
    def setup_method(self) -> None:
        self.source = LoopReturnsSource()
        self.team_id = 1
        self.config = LoopReturnsSourceConfig(api_key="loop_test_key")

    def test_get_schemas(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only the endpoints with a server-side `from`/`to` filter may claim incremental support.
        assert {name for name, schema in schemas.items() if schema.supports_incremental} == set(INCREMENTAL_FIELDS)
        assert [field["field"] for field in schemas["returns"].incremental_fields] == ["created_at", "updated_at"]
        assert [field["field"] for field in schemas["advanced_shipping_notices"].incremental_fields] == ["created_at"]

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
