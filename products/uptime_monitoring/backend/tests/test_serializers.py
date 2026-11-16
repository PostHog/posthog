from django.test import SimpleTestCase

from parameterized import parameterized

from products.uptime_monitoring.backend.presentation.serializers import (
    CREATE_NULL_MESSAGE,
    UPDATE_NULL_MESSAGE,
    CreateUptimeMonitorInputSerializer,
    UpdateUptimeMonitorInputSerializer,
)


class TestUptimeMonitorInputValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("name_too_long", {"name": "x" * 256}, "name"),
            ("null_name", {"name": None}, "name"),
            ("null_interval", {"interval_seconds": None}, "interval_seconds"),
            ("non_http_scheme", {"url": "ftp://example.com"}, "url"),
            ("not_a_url", {"url": "example"}, "url"),
            ("interval_below_minimum", {"interval_seconds": 30}, "interval_seconds"),
            ("interval_above_maximum", {"interval_seconds": 2 * 24 * 60 * 60}, "interval_seconds"),
            ("interval_between_minutes", {"interval_seconds": 90}, "interval_seconds"),
            ("timeout_above_maximum", {"timeout_seconds": 11}, "timeout_seconds"),
            ("unknown_method", {"method": "POST"}, "method"),
        ]
    )
    def test_rejects_invalid_input_on_create_and_update(self, _name: str, override: dict, field: str) -> None:
        for serializer_class, base in (
            (CreateUptimeMonitorInputSerializer, {"name": "Site", "url": "https://example.com"}),
            (UpdateUptimeMonitorInputSerializer, {}),
        ):
            serializer = serializer_class(data={**base, **override})
            assert not serializer.is_valid()
            assert field in serializer.errors

    @parameterized.expand(
        [
            ("create", CreateUptimeMonitorInputSerializer, CREATE_NULL_MESSAGE),
            ("update", UpdateUptimeMonitorInputSerializer, UPDATE_NULL_MESSAGE),
        ]
    )
    def test_null_error_says_what_to_do_instead(self, _name: str, serializer_class: type, message: str) -> None:
        serializer = serializer_class(data={"name": None, "url": None, "interval_seconds": None})
        assert not serializer.is_valid()
        for field in ("name", "url", "interval_seconds"):
            assert serializer.errors[field] == [message]

    def test_create_fills_defaults(self) -> None:
        serializer = CreateUptimeMonitorInputSerializer(data={"name": "Site", "url": "https://example.com"})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data.interval_seconds == 300
        assert serializer.validated_data.method == "GET"
