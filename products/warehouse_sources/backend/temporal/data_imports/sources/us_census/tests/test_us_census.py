import json
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.settings import (
    ENDPOINTS,
    MAX_VARIABLES_PER_QUERY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.us_census import (
    build_query_url,
    get_rows,
    parse_custom_variables,
    rows_from_payload,
    validate_credentials,
    validate_custom_query,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.us_census.us_census"


def _mock_response(
    status_code: int = 200,
    json_data: Any = None,
    headers: Optional[dict[str, str]] = None,
    text: str = "",
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = headers or {}
    response.text = text
    body = json.dumps(json_data).encode() if json_data is not None else text.encode()
    response.iter_content.return_value = iter([body])
    return response


def _patched_session(response: MagicMock):
    session = MagicMock()
    session.get.return_value = response
    return patch(f"{_MODULE}.make_tracked_session", return_value=session), session


class TestUSCensus:
    def test_build_query_url_keeps_census_syntax_literal(self):
        url = build_query_url(
            "2024/acs/acs5",
            ("NAME", "B01001_001E"),
            "county:*",
            geography_filter="state:06",
            api_key="secret",
        )

        assert url == (
            "https://api.census.gov/data/2024/acs/acs5?get=NAME,B01001_001E&for=county:*&in=state:06&key=secret"
        )

    def test_build_query_url_with_predicates_and_no_optional_parts(self):
        url = build_query_url("2023/cbp", ("ESTAB",), "state:*", predicates=(("NAICS2017", "00"),))

        assert url == "https://api.census.gov/data/2023/cbp?get=ESTAB&for=state:*&NAICS2017=00"

    def test_rows_from_payload_zips_header_row(self):
        payload = [
            ["NAME", "B01001_001E", "state"],
            ["California", "39242785", "06"],
            ["Texas", "29527941", "48"],
        ]

        assert rows_from_payload(payload) == [
            {"NAME": "California", "B01001_001E": "39242785", "state": "06"},
            {"NAME": "Texas", "B01001_001E": "29527941", "state": "48"},
        ]

    @pytest.mark.parametrize("payload", [None, {}, [], "rows", [{"NAME": "x"}]])
    def test_rows_from_payload_rejects_unexpected_shapes(self, payload):
        with pytest.raises(ValueError, match="Unexpected response"):
            rows_from_payload(payload)

    def test_get_rows_yields_row_dicts(self):
        payload = [["NAME", "state"], ["California", "06"], ["Texas", "48"]]
        patcher, session = _patched_session(_mock_response(json_data=payload))

        with patcher:
            batches = list(get_rows("key", "2024/acs/acs5", ("NAME",), "state:*", None, ()))

        assert batches == [[{"NAME": "California", "state": "06"}, {"NAME": "Texas", "state": "48"}]]
        requested_url = session.get.call_args.args[0]
        assert "key=key" in requested_url

    @pytest.mark.parametrize(
        ("headers", "location"),
        [
            ({"X-DataWebAPI-KeyError": "1"}, ""),
            ({}, "https://api.census.gov/data/invalid_key.html"),
            ({}, "https://api.census.gov/data/missing_key.html"),
        ],
    )
    def test_get_rows_raises_auth_error_on_key_redirect(self, headers, location):
        response = _mock_response(status_code=302, headers={**headers, "Location": location})

        patcher, _ = _patched_session(response)
        with patcher, pytest.raises(ValueError, match="US Census API key is missing or invalid"):
            list(get_rows("bad-key", "2024/acs/acs5", ("NAME",), "state:*", None, ()))

    def test_get_rows_surfaces_api_error_body(self):
        response = _mock_response(status_code=400, text="error: unknown variable 'B99999_999E'")

        patcher, _ = _patched_session(response)
        with patcher, pytest.raises(ValueError, match="unknown variable"):
            list(get_rows("key", "2024/acs/acs5", ("B99999_999E",), "state:*", None, ()))

    def test_get_rows_rejects_non_json_success_body(self):
        patcher, _ = _patched_session(_mock_response(text="<html>...</html>"))

        with patcher, pytest.raises(ValueError, match="not valid JSON"):
            list(get_rows("key", "2024/acs/acs5", ("NAME",), "state:*", None, ()))

    def test_get_rows_rejects_oversized_response(self):
        payload = [["NAME", "state"], ["California", "06"]]
        patcher, _ = _patched_session(_mock_response(json_data=payload))

        with patcher, patch(f"{_MODULE}._MAX_RESPONSE_BYTES", 8), pytest.raises(ValueError, match="too large"):
            list(get_rows("key", "2024/acs/acs5", ("NAME",), "state:*", None, ()))

    @pytest.mark.parametrize(
        ("status_code", "headers", "expected_valid", "expected_error_fragment"),
        [
            (200, {}, True, None),
            (302, {"X-DataWebAPI-KeyError": "1"}, False, "rejected"),
            (500, {}, False, "unexpected status"),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code, headers, expected_valid, expected_error_fragment):
        payload = [["NAME"], ["United States"]] if status_code == 200 else None
        patcher, _ = _patched_session(_mock_response(status_code=status_code, json_data=payload, headers=headers))

        with patcher:
            valid, error = validate_credentials("some-key")

        assert valid is expected_valid
        if expected_error_fragment is None:
            assert error is None
        else:
            assert error is not None and expected_error_fragment in error

    def test_validate_credentials_requires_key(self):
        valid, error = validate_credentials("  ")

        assert valid is False
        assert error is not None and "required" in error

    def test_validate_credentials_handles_network_failure(self):
        session = MagicMock()
        session.get.side_effect = ConnectionError("boom")

        with patch(f"{_MODULE}.make_tracked_session", return_value=session):
            valid, error = validate_credentials("some-key")

        assert valid is False
        assert error is not None and "Could not reach" in error

    def test_parse_custom_variables_strips_whitespace_and_empties(self):
        assert parse_custom_variables(" NAME , B01001_001E ,, ") == ("NAME", "B01001_001E")

    @pytest.mark.parametrize(
        ("dataset", "variables", "geography", "expected_fragment"),
        [
            (None, None, None, None),
            ("", "  ", "", None),
            ("2024/acs/acs5", "NAME", "state:*", None),
            ("2024/acs/acs5", None, None, "incomplete"),
            (None, "NAME", "state:*", "incomplete"),
            ("2024/acs/acs5?x=1", "NAME", "state:*", "dataset path is invalid"),
            ("2024/acs/acs5", " , ", "state:*", "variables are invalid"),
            (
                "2024/acs/acs5",
                ",".join(f"VAR{i}" for i in range(MAX_VARIABLES_PER_QUERY + 1)),
                "state:*",
                "too many variables",
            ),
        ],
    )
    def test_validate_custom_query(self, dataset, variables, geography, expected_fragment):
        error = validate_custom_query(dataset, variables, geography)

        if expected_fragment is None:
            assert error is None
        else:
            assert error is not None and expected_fragment in error

    @pytest.mark.parametrize("endpoint_name", list(ENDPOINTS))
    def test_endpoint_catalog_is_well_formed(self, endpoint_name):
        endpoint = ENDPOINTS[endpoint_name]

        assert 0 < len(endpoint.variables) <= MAX_VARIABLES_PER_QUERY
        assert len(set(endpoint.variables)) == len(endpoint.variables)
        assert ":" in endpoint.geography
        assert len(endpoint.primary_keys) > 0
        assert validate_custom_query(endpoint.dataset, ",".join(endpoint.variables), endpoint.geography) is None
