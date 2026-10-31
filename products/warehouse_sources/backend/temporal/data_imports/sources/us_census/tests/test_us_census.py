from typing import Any

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uscensus import (
    USCensusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.settings import (
    CUSTOM_QUERY_ENDPOINT,
    MAX_VARIABLES_PER_QUERY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.source import USCensusSource
from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.us_census import (
    build_query_url,
    rows_from_payload,
    validate_credentials,
    validate_custom_query,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.us_census.us_census"


def _run_query(api_key: str, variables: str, script: Any) -> DriveResult:
    config = USCensusSourceConfig(
        api_key=api_key,
        custom_dataset="2024/acs/acs5",
        custom_variables=variables,
        custom_geography="state:*",
    )
    return SourceDriver(USCensusSource(), config).run(CUSTOM_QUERY_ENDPOINT, script)


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

    @pytest.mark.parametrize("payload", [None, {}, [], "rows", [{"NAME": "x"}]])
    def test_rows_from_payload_rejects_unexpected_shapes(self, payload):
        with pytest.raises(ValueError, match="Unexpected response"):
            rows_from_payload(payload)

    def test_get_rows_yields_row_dicts(self):
        payload = [["NAME", "state"], ["California", "06"], ["Texas", "48"]]

        result = _run_query("key", "NAME", [ScriptedResponse(json=payload)])

        assert result.items == [[{"NAME": "California", "state": "06"}, {"NAME": "Texas", "state": "48"}]]
        assert result.requests[0].param("key") == "key"

    @pytest.mark.parametrize(
        ("headers", "location"),
        [
            ({"X-DataWebAPI-KeyError": "1"}, ""),
            ({}, "https://api.census.gov/data/invalid_key.html"),
            ({}, "https://api.census.gov/data/missing_key.html"),
        ],
    )
    def test_get_rows_raises_auth_error_on_key_redirect(self, headers, location):
        response_headers = {**headers, **({"Location": location} if location else {})}

        result = _run_query("bad-key", "NAME", [ScriptedResponse(status=302, headers=response_headers)])

        assert isinstance(result.raised, ValueError)
        assert "US Census API key is missing or invalid" in str(result.raised)

    def test_get_rows_surfaces_api_error_body(self):
        result = _run_query(
            "key",
            "B99999_999E",
            [ScriptedResponse(status=400, body=b"error: unknown variable 'B99999_999E'")],
        )

        assert isinstance(result.raised, ValueError)
        assert "unknown variable" in str(result.raised)

    def test_get_rows_rejects_non_json_success_body(self):
        result = _run_query("key", "NAME", [ScriptedResponse(body=b"<html>...</html>")])

        assert isinstance(result.raised, ValueError)
        assert "not valid JSON" in str(result.raised)

    def test_get_rows_rejects_oversized_response(self):
        payload = [["NAME", "state"], ["California", "06"]]

        with patch(f"{_MODULE}._MAX_RESPONSE_BYTES", 8):
            result = _run_query("key", "NAME", [ScriptedResponse(json=payload)])

        assert isinstance(result.raised, ValueError)
        assert "too large" in str(result.raised)

    @pytest.mark.parametrize(
        ("status_code", "headers", "expected_valid", "expected_error_fragment"),
        [
            (302, {"X-DataWebAPI-KeyError": "1"}, False, "rejected"),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code, headers, expected_valid, expected_error_fragment):
        payload = [["NAME"], ["United States"]] if status_code == 200 else None

        with scripted_network(always(ScriptedResponse(status=status_code, json=payload, headers=headers))):
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
