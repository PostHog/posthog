from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers

from products.warehouse_sources.backend.presentation.sync_frequency_field import (
    NEVER_SYNC_FREQUENCY_ERROR,
    SyncFrequencyField,
)

CANONICAL_VALUES = ["5min", "15min", "30min", "1hour", "6hour", "12hour", "24hour", "7day", "30day"]


class _Serializer(serializers.Serializer):
    sync_frequency = SyncFrequencyField(required=False, allow_null=True)


def _validate(value: object) -> serializers.Serializer:
    serializer = _Serializer(data={"sync_frequency": value})
    serializer.is_valid()
    return serializer


class TestSyncFrequencyField(SimpleTestCase):
    @parameterized.expand([(value, value) for value in CANONICAL_VALUES])
    def test_canonical_values_pass_through(self, value, expected):
        serializer = _validate(value)

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["sync_frequency"] == expected

    @parameterized.expand(
        [
            ("hourly", "1hour"),
            ("daily", "24hour"),
            ("weekly", "7day"),
            ("monthly", "30day"),
            ("1h", "1hour"),
            ("1hr", "1hour"),
            ("60min", "1hour"),
            ("60m", "1hour"),
            ("60 minutes", "1hour"),
            ("1 hour", "1hour"),
            ("1day", "24hour"),
            ("1d", "24hour"),
            ("24h", "24hour"),
            ("24hours", "24hour"),
            ("1440min", "24hour"),
            ("1week", "7day"),
            ("1w", "7day"),
            ("7d", "7day"),
            ("7days", "7day"),
            ("1month", "30day"),
            ("30d", "30day"),
            ("5m", "5min"),
            ("5minutes", "5min"),
            ("15 min", "15min"),
            ("30mins", "30min"),
            ("6h", "6hour"),
            ("12h", "12hour"),
            ("720min", "12hour"),
            ("every 6 hours", "6hour"),
            ("1_hour", "1hour"),
            ("1-hour", "1hour"),
            ("  Daily  ", "24hour"),
            ("DAILY", "24hour"),
            ("24HOUR", "24hour"),
        ]
    )
    def test_synonyms_map_to_canonical_value(self, value, expected):
        serializer = _validate(value)

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["sync_frequency"] == expected

    @parameterized.expand(
        [
            ("fortnightly",),
            ("2h",),
            ("1min",),
            ("1m",),
            ("90min",),
            ("0h",),
            ("every",),
            ("",),
            ("hour hour",),
            ("-5min",),
            ("+5min",),
            ("1-2h",),
            ("5-15min",),
            ("9" * 5000 + "min",),
            ("9" * 7 + "min",),
        ]
    )
    def test_unknown_value_lists_the_valid_values(self, value):
        serializer = _validate(value)

        assert not serializer.is_valid()
        message = str(serializer.errors["sync_frequency"][0])
        assert "is not a valid sync frequency" in message
        for canonical in CANONICAL_VALUES:
            assert canonical in message
        assert "never" not in message

    @parameterized.expand([("never",), ("Never",), (" NEVER ",)])
    def test_never_points_to_should_sync(self, value):
        serializer = _validate(value)

        assert not serializer.is_valid()
        assert str(serializer.errors["sync_frequency"][0]) == NEVER_SYNC_FREQUENCY_ERROR
        assert "should_sync" in NEVER_SYNC_FREQUENCY_ERROR

    def test_null_is_allowed(self):
        serializer = _validate(None)

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["sync_frequency"] is None

    @parameterized.expand([(60,), (True,), (["daily"],)])
    def test_non_string_input_is_rejected(self, value):
        assert not _validate(value).is_valid()

    def test_schema_enum_advertises_only_settable_values(self):
        assert list(SyncFrequencyField().choices) == CANONICAL_VALUES
