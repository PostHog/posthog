from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pardot import PardotSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pardot.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pardot.source import PardotSource

INCREMENTAL_ENDPOINTS = sorted(INCREMENTAL_FIELDS)
FULL_REFRESH_ENDPOINTS = sorted(set(ENDPOINTS) - set(INCREMENTAL_FIELDS))


def _integration(access_token: str | None = "access") -> mock.MagicMock:
    return mock.MagicMock(
        access_token=access_token,
        refresh_token="refresh",
        config={"instance_url": "https://acme.my.salesforce.com"},
    )


def _make_inputs(schema_name: str = "prospects", **overrides: Any) -> mock.MagicMock:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
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
        "api_version": None,
    }
    defaults.update(overrides)
    return mock.MagicMock(**defaults)


class TestPardotSource:
    def setup_method(self) -> None:
        self.source = PardotSource()
        self.team_id = 123
        self.config = PardotSourceConfig(
            business_unit_id="0Uv000000000000000",
            pardot_integration_id=7,
            environment="production",
        )

    def test_api_version_defaults_to_the_path_the_transport_calls(self) -> None:
        assert self.source.default_version == "v5"
        assert self.source.supported_versions == ("v5",)
        assert self.source.resolve_api_version(None) == "v5"

    @pytest.mark.parametrize(
        "probe_result",
        [(True, None), (False, "Account Engagement rejected the connection")],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pardot.source.validate_pardot_credentials"
    )
    def test_validate_credentials_probes_with_the_integration_token(
        self, mock_validate: mock.MagicMock, probe_result: tuple[bool, str | None]
    ) -> None:
        mock_validate.return_value = probe_result

        with mock.patch.object(PardotSource, "get_oauth_integration", return_value=_integration()):
            assert self.source.validate_credentials(self.config, self.team_id) == probe_result

        mock_validate.assert_called_once_with(
            environment="production",
            business_unit_id="0Uv000000000000000",
            access_token="access",
            refresh_token="refresh",
            instance_url="https://acme.my.salesforce.com",
        )

    @pytest.mark.parametrize(
        "patched",
        [
            # The integration was disconnected, or none was selected.
            {"side_effect": ValueError("Integration not found: 7")},
            # It exists but has no stored access token.
            {"return_value": _integration(access_token=None)},
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pardot.source.validate_pardot_credentials"
    )
    def test_validate_credentials_fails_cleanly_without_a_usable_integration(
        self, mock_validate: mock.MagicMock, patched: dict[str, Any]
    ) -> None:
        with mock.patch.object(PardotSource, "get_oauth_integration", **patched):
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message is not None
        mock_validate.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pardot.source.pardot_source")
    def test_source_for_pipeline_syncs_with_the_integration_credentials(
        self, mock_pardot_source: mock.MagicMock
    ) -> None:
        manager = mock.MagicMock()
        inputs = _make_inputs(
            "prospects",
            should_use_incremental_field=True,
            incremental_field="updatedAt",
            db_incremental_field_last_value="2024-05-01T00:00:00Z",
        )

        with mock.patch.object(PardotSource, "get_oauth_integration", return_value=_integration()) as get_integration:
            self.source.source_for_pipeline(self.config, manager, inputs)

        get_integration.assert_called_once_with(7, inputs.team_id)
        kwargs = mock_pardot_source.call_args.kwargs
        assert kwargs["access_token"] == "access"
        assert kwargs["refresh_token"] == "refresh"
        assert kwargs["instance_url"] == "https://acme.my.salesforce.com"
        assert kwargs["endpoint"] == "prospects"
        assert kwargs["api_version"] == "v5"
        assert kwargs["incremental_field"] == "updatedAt"
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"
        assert kwargs["resumable_source_manager"] is manager

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pardot.source.pardot_source")
    def test_full_refresh_run_drops_the_stored_watermark(self, mock_pardot_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            "prospects", should_use_incremental_field=False, db_incremental_field_last_value="2024-05-01T00:00:00Z"
        )

        with mock.patch.object(PardotSource, "get_oauth_integration", return_value=_integration()):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_pardot_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pardot.source.pardot_source")
    def test_sync_stops_when_the_integration_has_no_token(self, mock_pardot_source: mock.MagicMock) -> None:
        # Syncing on an empty token would fail every page with a 401 instead of naming the problem.
        with mock.patch.object(PardotSource, "get_oauth_integration", return_value=_integration(access_token=None)):
            with pytest.raises(ValueError, match="access token not found"):
                self.source.source_for_pipeline(self.config, mock.MagicMock(), _make_inputs())

        mock_pardot_source.assert_not_called()
