import pytest
from unittest.mock import Mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient


def _client() -> RESTClient:
    return RESTClient(base_url="https://api.example.com", session=Mock())


class TestRequiredDataSelector:
    def test_absent_key_raises_when_required(self) -> None:
        # The selector key is missing entirely -> response shape changed -> fail loud.
        with pytest.raises(ValueError, match="matched nothing"):
            _client()._extract_response({"unexpected": "envelope"}, "data", required=True)

    def test_present_empty_list_is_valid_zero_rows_when_required(self) -> None:
        # Key present, list empty -> a legit zero-row page, NOT a shape change -> no raise.
        assert _client()._extract_response({"data": []}, "data", required=True) == []

    def test_present_with_rows_when_required(self) -> None:
        assert _client()._extract_response({"data": [{"id": 1}]}, "data", required=True) == [{"id": 1}]

    def test_absent_key_is_silent_when_not_required(self) -> None:
        # Backward compatible: without required, a missing key still silently yields nothing.
        assert _client()._extract_response({"unexpected": "envelope"}, "data", required=False) == []

    @parameterized.expand([("empty_object", {}), ("empty_array", [])])
    def test_empty_body_raises_by_default_when_required(self, _name: str, body: object) -> None:
        # Without the opt-in, an empty container missing the key stays a fail-loud shape mismatch.
        with pytest.raises(ValueError, match="matched nothing"):
            _client()._extract_response(body, "data", required=True)

    @parameterized.expand([("empty_object", {}), ("empty_array", [])])
    def test_empty_body_is_zero_rows_when_empty_ok(self, _name: str, body: object) -> None:
        # With empty_body_ok, an empty container is a legit zero-row page -> for sources whose API
        # drops the envelope key for an empty collection (e.g. Cohere returns {} for no datasets).
        assert _client()._extract_response(body, "data", required=True, empty_body_ok=True) == []

    def test_non_empty_body_missing_key_still_raises_when_empty_ok(self) -> None:
        # empty_body_ok only relaxes empty containers; a body with other keys is still a shape change.
        with pytest.raises(ValueError, match="matched nothing"):
            _client()._extract_response({"unexpected": "envelope"}, "data", required=True, empty_body_ok=True)


class TestRequiredListBody:
    def test_non_list_body_raises_when_required_and_no_selector(self) -> None:
        with pytest.raises(ValueError, match="list response body"):
            _client()._extract_response({"error": "x"}, None, required=True)

    def test_list_body_ok_when_required_and_no_selector(self) -> None:
        assert _client()._extract_response([{"id": 1}], None, required=True) == [{"id": 1}]
