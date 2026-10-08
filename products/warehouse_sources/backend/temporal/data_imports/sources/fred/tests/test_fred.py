from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.fred.fred import (
    FredApiError,
    FredAuthenticationError,
    FredRequestError,
    FredResumeConfig,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fred.settings import (
    FRED_ENDPOINTS,
    FredEndpointConfig,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.fred.fred"


def _make_manager(resume_state: FredResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any = None, status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = {} if body is None else body
    return response


def _query(call: Any) -> dict[str, list[str]]:
    return parse_qs(urlparse(call.args[0]).query)


class TestFredTransport:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_every_request_asks_for_json(self, mock_session):
        # FRED defaults to XML; without file_type=json the response body isn't parseable.
        mock_session.return_value.get.return_value = _response({"seriess": [{"id": "UNRATE"}]})

        list(get_rows("key", ["UNRATE"], "series", mock.MagicMock(), _make_manager()))

        assert _query(mock_session.return_value.get.call_args)["file_type"] == ["json"]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_api_key_is_registered_for_redaction(self, mock_session):
        # The key rides in the query string, so the tracked transport has to mask it in
        # logged URLs and captured samples.
        mock_session.return_value.get.return_value = _response({"seriess": []})

        list(get_rows("secret-key", ["UNRATE"], "series", mock.MagicMock(), _make_manager()))

        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_paginated_endpoint_walks_offsets_until_short_page(self, mock_session):
        small_page = FredEndpointConfig(
            name="releases", path="/releases", data_key="releases", primary_keys=["id"], paginated=True, page_size=2
        )
        mock_session.return_value.get.side_effect = [
            _response({"releases": [{"id": 1}, {"id": 2}]}),
            _response({"releases": [{"id": 3}]}),
        ]

        with mock.patch.dict(FRED_ENDPOINTS, {"releases": small_page}):
            batches = list(get_rows("key", [], "releases", mock.MagicMock(), _make_manager()))

        assert batches == [[{"id": 1}, {"id": 2}], [{"id": 3}]]
        offsets = [_query(call).get("offset") for call in mock_session.return_value.get.call_args_list]
        assert offsets == [["0"], ["2"]]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resume_skips_completed_series_and_restarts_mid_offset(self, mock_session):
        small_page = FredEndpointConfig(
            name="observations",
            path="/series/observations",
            data_key="observations",
            primary_keys=["series_id", "date"],
            per_series=True,
            stamp_series_id=True,
            paginated=True,
            page_size=2,
        )
        mock_session.return_value.get.side_effect = [
            _response({"observations": [{"date": "2024-03-01"}]}),
            _response({"observations": [{"date": "2024-01-01"}]}),
        ]
        manager = _make_manager(FredResumeConfig(series_index=1, offset=4))

        with mock.patch.dict(FRED_ENDPOINTS, {"observations": small_page}):
            list(get_rows("key", ["UNRATE", "CPIAUCSL", "GDPC1"], "observations", mock.MagicMock(), manager))

        calls = mock_session.return_value.get.call_args_list
        assert [_query(call)["series_id"][0] for call in calls] == ["CPIAUCSL", "GDPC1"]
        # The saved offset applies only to the series it was saved against.
        assert [_query(call)["offset"][0] for call in calls] == ["4", "0"]

    @pytest.mark.parametrize(
        "status_code, error_message, expected_exception",
        [
            (400, "Bad Request.  The value for variable api_key is not registered.", FredAuthenticationError),
            (400, "Bad Request.  The series does not exist.", FredRequestError),
            (401, "", FredAuthenticationError),
            (403, "", FredAuthenticationError),
            (429, "Too Many Requests.", FredApiError),
            (500, "", FredApiError),
        ],
    )
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_error_status_mapping(self, mock_session, status_code, error_message, expected_exception):
        mock_session.return_value.get.return_value = _response(
            {"error_code": status_code, "error_message": error_message}, status_code=status_code
        )

        with pytest.raises(expected_exception):
            list(get_rows("key", ["UNRATE"], "series", mock.MagicMock(), _make_manager()))

    @pytest.mark.parametrize("status_code", [400, 401, 429, 500])
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_errors_never_leak_the_api_key(self, mock_session, status_code):
        # The key travels as a query param, so an exception built from the request URL would
        # write it into logs and into the failure surfaced to the user.
        mock_session.return_value.get.return_value = _response(
            {"error_message": "Bad Request. The value for variable api_key is not registered."},
            status_code=status_code,
        )

        with pytest.raises(FredApiError) as error:
            list(get_rows("super-secret", ["UNRATE"], "series", mock.MagicMock(), _make_manager()))

        assert "super-secret" not in str(error.value)

    @pytest.mark.parametrize(
        "raised",
        [
            requests.ConnectionError(
                "HTTPSConnectionPool(host='api.stlouisfed.org', port=443): Max retries exceeded with "
                "url: /fred/series?series_id=UNRATE&api_key=super-secret&file_type=json"
            ),
            requests.ReadTimeout(
                "HTTPSConnectionPool(host='api.stlouisfed.org', port=443): Read timed out. "
                "url: /fred/series?api_key=super-secret"
            ),
        ],
    )
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_transport_errors_never_leak_the_api_key(self, mock_session, raised):
        # requests' own connection/timeout exceptions embed the prepared URL, api_key and all,
        # and the pipeline persists that text as `latest_error`.
        mock_session.return_value.get.side_effect = raised

        with pytest.raises(FredApiError) as error:
            list(get_rows("super-secret", ["UNRATE"], "series", mock.MagicMock(), _make_manager()))

        assert "super-secret" not in str(error.value)
        # `from None` so the suppressed original can't be re-rendered into the chained message.
        assert error.value.__cause__ is None
        assert error.value.__suppress_context__
        assert type(raised).__name__ in str(error.value)

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_transport_errors_stay_retryable(self, mock_session):
        # A dropped connection is not a bad key or a bad series id, so it must not match one of
        # the source's non-retryable error prefixes.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        with pytest.raises(FredApiError) as error:
            list(get_rows("key", ["UNRATE"], "series", mock.MagicMock(), _make_manager()))

        assert not isinstance(error.value, FredAuthenticationError | FredRequestError)
        assert not str(error.value).startswith(("FRED authentication failed", "FRED rejected the request"))

    @pytest.mark.parametrize(
        "body, expected_type",
        [
            # FRED serves HTML from its edge on some failures, so the body may not be JSON at all.
            (ValueError("not json"), FredApiError),
            # ...and a JSON body that isn't an object has no `error_message` to read.
            (["unexpected"], FredApiError),
        ],
    )
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_unparseable_error_bodies_still_raise(self, mock_session, body, expected_type):
        response = _response(status_code=500)
        if isinstance(body, Exception):
            response.json.side_effect = body
        else:
            response.json.return_value = body
        mock_session.return_value.get.return_value = response

        with pytest.raises(expected_type) as error:
            list(get_rows("key", ["UNRATE"], "series", mock.MagicMock(), _make_manager()))

        assert "status=500" in str(error.value)

    @pytest.mark.parametrize(
        "status_code, error_message, expected",
        [
            (200, "", (True, None)),
            (
                400,
                "Bad Request.  The value for variable api_key is not registered.",
                (False, "Invalid FRED API key. Check the key you requested at fred.stlouisfed.org."),
            ),
            (
                400,
                "Bad Request.  The series does not exist.",
                (False, "FRED has no series with the ID NOPE. Check it on fred.stlouisfed.org."),
            ),
            (500, "", (False, "Could not reach the FRED API. Try again in a moment.")),
        ],
    )
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, error_message, expected):
        mock_session.return_value.get.return_value = _response(
            {"seriess": [], "error_message": error_message}, status_code=status_code
        )

        assert validate_credentials("key", "NOPE") == expected
