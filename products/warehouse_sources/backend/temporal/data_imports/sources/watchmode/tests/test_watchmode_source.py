import pytest
from unittest.mock import MagicMock, patch

import requests

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.watchmode import (
    WatchmodeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.source import WatchmodeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.watchmode import WatchmodeResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestWatchmodeSource:
    def setup_method(self) -> None:
        self.source = WatchmodeSource()
        self.config = WatchmodeSourceConfig(api_key="test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.WATCHMODE

    def test_source_is_released_as_alpha(self) -> None:
        config = self.source.get_source_config

        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_get_schemas_are_all_full_refresh(self) -> None:
        # No Watchmode endpoint has a server-side timestamp filter usable for incremental
        # sync; flipping one to incremental without such a filter would corrupt syncs.
        schemas = self.source.get_schemas(self.config, team_id=1)

        assert [s.name for s in schemas] == list(ENDPOINTS)
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["titles", "genres"])

        assert {s.name for s in schemas} == {"titles", "genres"}

    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    def test_validate_credentials_maps_status_codes(self, status_code: int, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.watchmode.make_tracked_session"
        ) as mock_make_session:
            response = requests.Response()
            response.status_code = status_code
            mock_make_session.return_value.get.return_value = response

            valid, error = self.source.validate_credentials(self.config, team_id=1)

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error

    def test_validate_credentials_sends_key_in_header_not_url(self) -> None:
        # The key must ride in the X-API-Key header, never the query string, so it can't
        # leak into access/proxy logs that record request URLs.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.watchmode.make_tracked_session"
        ) as mock_make_session:
            response = requests.Response()
            response.status_code = 200
            mock_get = mock_make_session.return_value.get
            mock_get.return_value = response

            self.source.validate_credentials(self.config, team_id=1)

        called_url = mock_get.call_args.args[0] if mock_get.call_args.args else mock_get.call_args.kwargs["url"]
        assert "test-key" not in called_url
        assert "apiKey" not in called_url
        assert mock_get.call_args.kwargs["headers"] == {"X-API-Key": "test-key"}

    def test_validate_credentials_disables_redirects(self) -> None:
        # A cross-host redirect would otherwise replay the `X-API-Key` header off-host,
        # leaking the key; the validation probe must pin redirects off.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.watchmode.make_tracked_session"
        ) as mock_make_session:
            response = requests.Response()
            response.status_code = 200
            mock_make_session.return_value.get.return_value = response

            self.source.validate_credentials(self.config, team_id=1)

        assert mock_make_session.call_args.kwargs["allow_redirects"] is False

    def test_validate_credentials_handles_connection_errors(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.watchmode.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.side_effect = requests.ConnectionError("connection refused")

            valid, error = self.source.validate_credentials(self.config, team_id=1)

        assert valid is False
        assert error is not None and "Watchmode" in error

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_http_errors_are_non_retryable(self, status_code: int) -> None:
        # A bad API key must fail the sync permanently instead of retrying forever, so
        # the patterns have to match the exact HTTPError text raise_for_status produces.
        response = requests.Response()
        response.status_code = status_code
        response.url = "https://api.watchmode.com/v1/list-titles/"
        response.reason = "Unauthorized" if status_code == 401 else "Forbidden"

        with pytest.raises(requests.HTTPError) as exc_info:
            response.raise_for_status()

        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(pattern in str(exc_info.value) for pattern in non_retryable_errors)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WatchmodeResumeConfig

    def test_source_for_pipeline_plumbs_config_and_inputs(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "titles"
        inputs.team_id = 42
        inputs.job_id = "job-1"
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.source.watchmode_source"
        ) as mock_source:
            result = self.source.source_for_pipeline(self.config, manager, inputs)

        assert result is mock_source.return_value
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "test-key"
        assert kwargs["endpoint"] == "titles"
        assert kwargs["team_id"] == 42
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
