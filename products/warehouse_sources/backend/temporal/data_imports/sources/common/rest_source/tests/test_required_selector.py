import pytest
from unittest.mock import Mock

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
