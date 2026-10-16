import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fred.fred import (
    FredApiError,
    FredAuthenticationError,
    FredRequestError,
    FredResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fred.settings import (
    FRED_ENDPOINTS,
    FredEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fred.source import FredSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fred import FredSourceConfig


class TestFredTransport:
    @staticmethod
    def _driver(series_ids: str = "UNRATE", api_key: str = "key") -> SourceDriver:
        return SourceDriver(FredSource(), FredSourceConfig(api_key=api_key, series_ids=series_ids))

    def test_every_request_asks_for_json(self):
        # FRED defaults to XML; without file_type=json the response body isn't parseable.
        result = self._driver().run("series", [ScriptedResponse(json={"seriess": [{"id": "UNRATE"}]})])

        assert result.raised is None
        assert result.rows == [{"id": "UNRATE"}]
        assert result.params("file_type") == ["json"]

    def test_api_key_is_registered_for_redaction(self):
        # The key rides in the query string, so the tracked transport has to mask it in
        # logged URLs and captured samples.
        result = self._driver(api_key="secret-key").run("series", [ScriptedResponse(json={"seriess": []})])

        assert result.raised is None
        assert result.session_options == [{"redact_values": ("secret-key",)}]

    def test_paginated_endpoint_walks_offsets_until_short_page(self):
        small_page = FredEndpointConfig(
            name="releases", path="/releases", data_key="releases", primary_keys=["id"], paginated=True, page_size=2
        )
        with mock.patch.dict(FRED_ENDPOINTS, {"releases": small_page}):
            result = self._driver().run(
                "releases",
                [
                    ScriptedResponse(json={"releases": [{"id": 1}, {"id": 2}]}),
                    ScriptedResponse(json={"releases": [{"id": 3}]}),
                ],
            )

        assert result.raised is None
        assert result.items == [[{"id": 1}, {"id": 2}], [{"id": 3}]]
        assert result.params("offset") == ["0", "2"]

    def test_resume_skips_completed_series_and_restarts_mid_offset(self):
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
        with mock.patch.dict(FRED_ENDPOINTS, {"observations": small_page}):
            result = self._driver("UNRATE, CPIAUCSL, GDPC1").run(
                "observations",
                [
                    ScriptedResponse(json={"observations": [{"date": "2024-03-01"}]}),
                    ScriptedResponse(json={"observations": [{"date": "2024-01-01"}]}),
                ],
                resume_state=FredResumeConfig(series_index=1, offset=4),
            )

        assert result.raised is None
        assert result.params("series_id") == ["CPIAUCSL", "GDPC1"]
        # The saved offset applies only to the series it was saved against.
        assert result.params("offset") == ["4", "0"]
        assert result.rows == [
            {"date": "2024-03-01", "series_id": "CPIAUCSL"},
            {"date": "2024-01-01", "series_id": "GDPC1"},
        ]

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
    def test_error_status_mapping(self, status_code, error_message, expected_exception):
        response = ScriptedResponse(
            status=status_code, json={"error_code": status_code, "error_message": error_message}
        )
        result = self._driver().run("series", [response] * (4 if status_code in (429, 500) else 1))

        assert isinstance(result.raised, expected_exception)

    @pytest.mark.parametrize("status_code", [400, 401, 429, 500])
    def test_errors_never_leak_the_api_key(self, status_code):
        # The key travels as a query param, so an exception built from the request URL would
        # write it into logs and into the failure surfaced to the user.
        response = ScriptedResponse(
            status=status_code,
            json={"error_message": "Bad Request. The value for variable api_key is not registered."},
        )
        result = self._driver(api_key="super-secret").run(
            "series", [response] * (4 if status_code in (429, 500) else 1)
        )

        assert isinstance(result.raised, FredApiError)
        assert "super-secret" not in str(result.raised)

    @pytest.mark.parametrize(
        "raised",
        [
            ConnectionResetError(
                "HTTPSConnectionPool(host='api.stlouisfed.org', port=443): Max retries exceeded with "
                "url: /fred/series?series_id=UNRATE&api_key=super-secret&file_type=json"
            ),
            TimeoutError(
                "HTTPSConnectionPool(host='api.stlouisfed.org', port=443): Read timed out. "
                "url: /fred/series?api_key=super-secret"
            ),
        ],
    )
    def test_transport_errors_never_leak_the_api_key(self, raised):
        # A connection or timeout error can contain the prepared URL and API key.
        result = self._driver(api_key="super-secret").run("series", [raised] * 4)

        assert isinstance(result.raised, FredApiError)
        assert "super-secret" not in str(result.raised)
        # `from None` so the suppressed original can't be re-rendered into the chained message.
        assert result.raised.__cause__ is None
        assert result.raised.__suppress_context__
        # A read that still times out after the transport's retries surfaces as a connection error.
        assert "ConnectionError" in str(result.raised)

    def test_transport_errors_stay_retryable(self):
        # A dropped connection is not a bad key or a bad series id, so it must not match one of
        # the source's non-retryable error prefixes.
        result = self._driver().run("series", [ConnectionResetError("boom")] * 4)

        assert isinstance(result.raised, FredApiError)
        assert not isinstance(result.raised, FredAuthenticationError | FredRequestError)
        assert not str(result.raised).startswith(("FRED authentication failed", "FRED rejected the request"))

    @pytest.mark.parametrize(
        "body, expected_type",
        [
            # FRED serves HTML from its edge on some failures, so the body may not be JSON at all.
            (ValueError("not json"), FredApiError),
            # ...and a JSON body that isn't an object has no `error_message` to read.
            (["unexpected"], FredApiError),
        ],
    )
    def test_unparseable_error_bodies_still_raise(self, body, expected_type):
        response = (
            ScriptedResponse(status=500, body=b"<html>error</html>")
            if isinstance(body, Exception)
            else ScriptedResponse(status=500, json=body)
        )
        result = self._driver().run("series", [response] * 4)

        assert isinstance(result.raised, expected_type)
        assert "status=500" in str(result.raised)

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
    def test_validate_credentials_status_mapping(self, status_code, error_message, expected):
        response = ScriptedResponse(status=status_code, json={"seriess": [], "error_message": error_message})
        with scripted_network([response] * (4 if status_code == 500 else 1)) as network:
            actual = validate_credentials("key", "NOPE")

        assert actual == expected
        assert network.requests_log
        assert {request.param("series_id") for request in network.requests_log} == {"NOPE"}
