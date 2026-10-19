import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import (
    UNSUPPORTED_SYNC_TYPE_ERROR,
    ExternalDataSchema,
    UnsupportedSyncTypeError,
    resolve_sync_type,
)
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import Any_Source_Errors


class TestResolveSyncType(SimpleTestCase):
    @parameterized.expand(
        [
            ("none", None, None),
            ("full_refresh", "full_refresh", ExternalDataSchema.SyncType.FULL_REFRESH),
            ("incremental", "incremental", ExternalDataSchema.SyncType.INCREMENTAL),
            ("legacy_full", "full", ExternalDataSchema.SyncType.FULL_REFRESH),
        ]
    )
    def test_resolves(self, _name, stored, expected):
        assert resolve_sync_type(stored) == expected

    @parameterized.expand([("unknown", "bogus"), ("wrong_case", "Full"), ("empty", "")])
    def test_unsupported_value_raises_error_that_disables_the_schema(self, _name, stored):
        with pytest.raises(UnsupportedSyncTypeError) as exc_info:
            resolve_sync_type(stored)

        assert any(marker in str(exc_info.value) for marker in Any_Source_Errors)
        assert str(exc_info.value).startswith(UNSUPPORTED_SYNC_TYPE_ERROR)
