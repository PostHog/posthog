from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.source import AsknicelySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.asknicely import (
    AsknicelySourceConfig,
)


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "responses",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestAsknicelySource:
    def setup_method(self) -> None:
        self.source = AsknicelySource()
        self.team_id = 123
        self.config = AsknicelySourceConfig(subdomain="acme", api_key="test-key")

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [s.name for s in schemas] == ["responses"]
        responses = schemas[0]
        assert responses.supports_incremental is True
        assert responses.supports_append is True
        assert [f["field"] for f in responses.incremental_fields] == ["responded"]

    @pytest.mark.parametrize("subdomain", ["not a subdomain", "acme.asknice.ly", "evil/../path", ""])
    def test_validate_credentials_rejects_bad_subdomain_without_a_request(self, subdomain: str) -> None:
        config = AsknicelySourceConfig(subdomain=subdomain, api_key="test-key")

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.source.validate_asknicely_credentials"
        ) as mock_validate:
            is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message is not None and "subdomain" in error_message
        mock_validate.assert_not_called()

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid"),
        [
            ((True, None), True),
            ((False, "Invalid AskNicely API key"), False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.source.validate_asknicely_credentials"
    )
    def test_validate_credentials_delegates_to_transport(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, str | None],
        expected_valid: bool,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == mock_return[1]
        mock_validate.assert_called_once_with("acme", "test-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.source.asknicely_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark left over from a previous incremental run must not leak into a
        # full-refresh sync, or the refresh would silently skip older responses.
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value=1700000000)

        self.source.source_for_pipeline(self.config, mock.MagicMock(spec=ResumableSourceManager), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
