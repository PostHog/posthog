import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import DEFAULT_RETRY
from products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit import DOIT_RETRY
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
