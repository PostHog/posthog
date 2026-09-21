import json
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.us_bea.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.us_bea.us_bea import (
    UsBeaAuthenticationError,
    UsBeaRequestError,
    UsBeaResponseTooLargeError,
    build_query_url,
    get_data_rows,
    get_endpoint_rows,
    parse_custom_query_params,
    validate_credentials,
    validate_custom_query,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.us_bea.us_bea"


def _mock_response(status_code: int = 200, json_data: Any = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = json_data
    # _fetch reads the body via stream=True + iter_content, not response.json()/response.text.
    body = json.dumps(json_data).encode("utf-8") if json_data is not None else b""
    response.iter_content.return_value = iter([body]) if body else iter([])
    return response


def _patched_session(*responses: MagicMock):
    session = MagicMock()
    session.get.side_effect = list(responses) if len(responses) > 1 else None
    if len(responses) == 1:
        session.get.return_value = responses[0]
    return patch(f"{_MODULE}.make_tracked_session", return_value=session), session


def _data_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"BEAAPI": {"Results": {"Data": rows}}}


def _error_payload(code: str, description: str) -> dict[str, Any]:
    return {"BEAAPI": {"Results": {"Error": {"APIErrorCode": code, "APIErrorDescription": description}}}}


class TestUsBea:
    def test_build_query_url_includes_user_id_and_method(self):
        url = build_query_url("secret-id", "GetData", "Regional", {"TableName": "SAINC1"})

        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        assert query["UserID"] == ["secret-id"]
        assert query["method"] == ["GetData"]
        assert query["datasetname"] == ["Regional"]
        assert query["TableName"] == ["SAINC1"]
        assert query["ResultFormat"] == ["JSON"]

    def test_build_query_url_omits_dataset_name_when_not_given(self):
        url = build_query_url("secret-id", "GetDatasetList")

        assert "datasetname" not in parse_qs(urlparse(url).query)

    def test_get_data_rows_returns_data_list(self):
        rows = [{"Code": "SAINC1-1", "GeoFips": "01000", "DataValue": "35706"}]
        response = _mock_response(json_data=_data_payload(rows))
        session = MagicMock()
        session.get.return_value = response

        result = get_data_rows(session, "user-id", "Regional", {"TableName": "SAINC1"})

        assert result == rows

    def test_get_data_rows_handles_single_dict_data_node(self):
        row = {"Code": "SAINC1-1", "GeoFips": "01000"}
        response = _mock_response(json_data={"BEAAPI": {"Results": {"Data": row}}})
        session = MagicMock()
        session.get.return_value = response

        assert get_data_rows(session, "user-id", "Regional", {}) == [row]

    def test_get_data_rows_handles_multi_result_list(self):
        payload = {
            "BEAAPI": {
                "Results": [
                    {"Data": [{"Code": "A"}]},
                    {"Data": [{"Code": "B"}]},
                ]
            }
        }
        response = _mock_response(json_data=payload)
        session = MagicMock()
        session.get.return_value = response

        assert get_data_rows(session, "user-id", "Regional", {}) == [{"Code": "A"}, {"Code": "B"}]

    def test_get_data_rows_raises_authentication_error_on_invalid_user_id(self):
        response = _mock_response(json_data=_error_payload("1", "Invalid Request - Invalid API UserId."))
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(UsBeaAuthenticationError):
            get_data_rows(session, "bad-id", "Regional", {})

    def test_get_data_rows_raises_request_error_on_other_api_errors(self):
        response = _mock_response(
            json_data=_error_payload(
                "34", "The GetParameterValuesFiltered method has not been implemented on this dataset (coming soon)."
            )
        )
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(UsBeaRequestError):
            get_data_rows(session, "user-id", "Regional", {})

    def test_get_data_rows_raises_when_response_body_exceeds_size_cap(self):
        response = _mock_response(json_data=_data_payload([{"Code": "SAINC1-1"}]))
        response.iter_content.return_value = iter([b"a" * 1024, b"b" * 1024])
        session = MagicMock()
        session.get.return_value = response

        with patch(f"{_MODULE}._MAX_RESPONSE_BYTES", 1500):
            with pytest.raises(UsBeaResponseTooLargeError):
                get_data_rows(session, "user-id", "Regional", {})

    def test_fetch_streams_the_request_instead_of_buffering_it_whole(self):
        response = _mock_response(json_data=_data_payload([{"Code": "SAINC1-1"}]))
        session = MagicMock()
        session.get.return_value = response

        get_data_rows(session, "user-id", "Regional", {})

        assert session.get.call_args.kwargs["stream"] is True
        response.json.assert_not_called()
        response.close.assert_called_once()

    def test_get_endpoint_rows_issues_one_call_per_line_code_and_merges(self):
        endpoint = ENDPOINTS["StatePersonalIncomeSummary"]
        responses = [
            _mock_response(json_data=_data_payload([{"Code": f"SAINC1-{code}"}])) for code in endpoint.line_codes
        ]
        patcher, session = _patched_session(*responses)

        with patcher:
            batches = list(get_endpoint_rows("user-id", endpoint))

        assert session.get.call_count == len(endpoint.line_codes)
        assert [row for batch in batches for row in batch] == [
            {"Code": f"SAINC1-{code}"} for code in endpoint.line_codes
        ]
        requested_line_codes = [
            parse_qs(urlparse(call.args[0]).query)["LineCode"][0] for call in session.get.call_args_list
        ]
        assert requested_line_codes == list(endpoint.line_codes)

    def test_parse_custom_query_params_strips_whitespace_and_ignores_malformed_pairs(self):
        assert parse_custom_query_params(" TableName=T10101 , Frequency=Q ,, garbage ") == {
            "TableName": "T10101",
            "Frequency": "Q",
        }

    @pytest.mark.parametrize(
        ("dataset_name", "params_raw", "expected_fragment"),
        [
            (None, None, None),
            ("", "  ", None),
            ("NIPA", "TableName=T10101,Frequency=Q,Year=ALL", None),
            ("NIPA", None, "incomplete"),
            (None, "TableName=T10101", "incomplete"),
            ("NIPA/2", "TableName=T10101", "dataset name is invalid"),
            ("NIPA", ",  ,", "parameters are invalid"),
        ],
    )
    def test_validate_custom_query(
        self, dataset_name: Optional[str], params_raw: Optional[str], expected_fragment: Optional[str]
    ):
        error = validate_custom_query(dataset_name, params_raw)

        if expected_fragment is None:
            assert error is None
        else:
            assert error is not None and expected_fragment in error

    def test_validate_credentials_requires_user_id(self):
        valid, error = validate_credentials("   ")

        assert valid is False
        assert error is not None and "missing or invalid" in error

    def test_validate_credentials_success(self):
        response = _mock_response(json_data={"BEAAPI": {"Results": {"Parameter": []}}})
        patcher, _ = _patched_session(response)

        with patcher:
            valid, error = validate_credentials("user-id")

        assert (valid, error) == (True, None)

    def test_validate_credentials_rejects_invalid_user_id(self):
        response = _mock_response(json_data=_error_payload("1", "Invalid Request - Invalid API UserId."))
        patcher, _ = _patched_session(response)

        with patcher:
            valid, error = validate_credentials("bad-id")

        assert valid is False
        assert error is not None and "missing or invalid" in error

    def test_validate_credentials_handles_network_failure(self):
        session = MagicMock()
        session.get.side_effect = ConnectionError("boom")

        with patch(f"{_MODULE}.make_tracked_session", return_value=session):
            valid, error = validate_credentials("user-id")

        assert valid is False
        assert error is not None and "Could not reach" in error

    @pytest.mark.parametrize("endpoint_name", list(ENDPOINTS))
    def test_endpoint_catalog_is_well_formed(self, endpoint_name: str):
        endpoint = ENDPOINTS[endpoint_name]

        assert endpoint.dataset_name
        assert endpoint.table_name
        assert len(endpoint.line_codes) > 0
        assert len(set(endpoint.line_codes)) == len(endpoint.line_codes)
        assert "Year" in endpoint.extra_params
        assert len(endpoint.primary_keys) > 0
