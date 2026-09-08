import pytest
from unittest.mock import MagicMock, patch

from django.db import OperationalError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.byte_bounded_extraction_flag import (
    is_byte_bounded_extraction_enabled,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.byte_bounded_extraction_flag"


class TestByteBoundedExtractionFlagFailsClosed:
    def test_flag_service_error_returns_false(self):
        with (
            patch(f"{_MODULE}.Team") as team_cls,
            patch(f"{_MODULE}.posthoganalytics.feature_enabled", side_effect=RuntimeError("flags endpoint down")),
        ):
            team_cls.objects.get.return_value.uuid = "u"
            assert is_byte_bounded_extraction_enabled(1, "MySQL") is False

    @pytest.mark.django_db
    def test_missing_team_returns_false(self):
        assert is_byte_bounded_extraction_enabled(999999999, "MySQL") is False

    def test_transient_db_connection_drop_is_retried(self):
        with (
            patch(f"{_MODULE}.Team") as team_cls,
            patch(f"{_MODULE}.posthoganalytics.feature_enabled", return_value=True),
        ):
            team_cls.objects.only.return_value.get.side_effect = [
                OperationalError("[Errno -2] Name or service not known"),
                MagicMock(),
            ]
            assert is_byte_bounded_extraction_enabled(1, "MySQL") is True

    def test_source_type_reaches_the_flag_for_per_driver_targeting(self):
        with (
            patch(f"{_MODULE}.Team") as team_cls,
            patch(f"{_MODULE}.posthoganalytics.feature_enabled", return_value=True) as feature_enabled,
        ):
            team_cls.objects.get.return_value.uuid = "u"
            assert is_byte_bounded_extraction_enabled(1, "MySQL") is True

        assert feature_enabled.call_args.kwargs["person_properties"]["source_type"] == "MySQL"
