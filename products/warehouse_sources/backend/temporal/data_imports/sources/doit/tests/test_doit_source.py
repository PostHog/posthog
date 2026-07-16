import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import DEFAULT_RETRY
from products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit import (
    DOIT_MAX_RETRIES,
    DOIT_RETRY,
    DoItRetryableError,
    _doit_get,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.doit.source import DoItSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestDoItSource:
    def setup_method(self):
        self.source = DoItSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.DOIT

    @pytest.mark.parametrize("pattern", ["Report no longer exists"])
    def test_non_retryable_errors_includes_pattern(self, pattern):
        errors = self.source.get_non_retryable_errors()

        assert pattern in errors

    @pytest.mark.parametrize("status_code", [520, 521, 522, 523, 524])
    def test_doit_retry_includes_cloudflare_transient_statuses(self, status_code):
        assert status_code in (DOIT_RETRY.status_forcelist or ())

    def test_doit_retry_preserves_default_statuses(self):
        assert set(DEFAULT_RETRY.status_forcelist or ()).issubset(set(DOIT_RETRY.status_forcelist or ()))


class TestDoItGet:
    """`_doit_get` backs off on transient 429/5xx responses instead of failing the sync."""

    def setup_method(self):
        # Disable tenacity's real backoff so the retry loop runs instantly. tenacity attaches
        # the controlling `Retrying` instance as `.retry` at decoration time (runtime-only).
        _doit_get.retry.sleep = lambda *args, **kwargs: None  # type: ignore[attr-defined]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit.make_tracked_session")
    def test_retries_then_succeeds_on_transient_429(self, mock_session):
        rate_limited = mock.MagicMock(status_code=429)
        ok = mock.MagicMock(status_code=200)
        mock_session.return_value.get.side_effect = [rate_limited, ok]

        assert _doit_get("https://api.doit.com/x", "key") is ok
        assert mock_session.return_value.get.call_count == 2

    @pytest.mark.parametrize("status_code", [429, 500, 503])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit.make_tracked_session")
    def test_raises_retryable_after_exhausting_transient_status(self, mock_session, status_code):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        with pytest.raises(DoItRetryableError):
            _doit_get("https://api.doit.com/x", "key")
        assert mock_session.return_value.get.call_count == DOIT_MAX_RETRIES

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit.make_tracked_session")
    def test_returns_client_error_without_retrying(self, mock_session):
        # A 404 is deterministic — return it so the caller raises its own descriptive error.
        not_found = mock.MagicMock(status_code=404)
        mock_session.return_value.get.return_value = not_found

        assert _doit_get("https://api.doit.com/x", "key") is not_found
        assert mock_session.return_value.get.call_count == 1
