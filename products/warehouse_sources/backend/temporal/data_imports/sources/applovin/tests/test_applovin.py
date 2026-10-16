from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote, quote_plus

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.applovin import (
    AUTH_ERROR_PREFIX,
    BAD_REQUEST_ERROR_PREFIX,
    TRANSIENT_ERROR_PREFIX,
    AppLovinAPIError,
    AppLovinResumeConfig,
    _body_code,
    _to_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.settings import (
    APPLOVIN_ENDPOINTS,
    ENDPOINTS,
    MAX_REQUEST_WINDOW_DAYS,
    REPORT_LOOKBACK_DAYS,
    REPORT_PAGE_SIZE,
    REPORT_WINDOW_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.source import AppLovinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applovin import (
    AppLovinSourceConfig,
)


def _driver(api_key: str = "key") -> SourceDriver:
    return SourceDriver(AppLovinSource(), AppLovinSourceConfig(api_key=api_key))


def _page(rows: Any = None) -> ScriptedResponse:
    return ScriptedResponse(json={"code": 200, "results": rows})


def _rows(count: int) -> list[dict[str, str]]:
    return [{"day": "2026-07-01", "package_name": f"com.app.{index}"} for index in range(count)]


def _today() -> date:
    return datetime.now(tz=UTC).date()


def _earliest() -> date:
    return _today() - timedelta(days=MAX_REQUEST_WINDOW_DAYS - 1)


class TestHelpers:
    @pytest.mark.parametrize(
        "value, expected_iso",
        [
            (datetime(2026, 7, 2, 3, 4, 5, tzinfo=UTC), "2026-07-02"),
            (date(2026, 7, 2), "2026-07-02"),
            ("2026-07-02", "2026-07-02"),
            ("2026-07-02T03:04:05Z", "2026-07-02"),
            ("junk", None),
            (None, None),
            (12345, None),
        ],
    )
    def test_to_date(self, value: Any, expected_iso: Optional[str]) -> None:
        result = _to_date(value)
        assert (result.isoformat() if result else None) == expected_iso

    @pytest.mark.parametrize(
        "body, expected",
        [
            ({"code": 200}, 200),
            ({"code": "200"}, 200),
            ({"code": 403}, 403),
            ({"results": []}, None),
            ({"code": None}, None),
            ({"code": "nope"}, None),
            ("Authentication Failed", None),
        ],
    )
    def test_body_code(self, body: Any, expected: Optional[int]) -> None:
        assert _body_code(body) == expected


class TestRequestShape:
    def test_report_key_is_registered_for_redaction(self) -> None:
        result = _driver("secret-key").run("max_ad_revenue", [_page([]) for _ in range(7)])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("secret-key",)


class TestWindowWalking:
    def test_checkpoint_survives_a_failed_walk(self) -> None:
        first_window = _earliest()
        second_window = first_window + timedelta(days=REPORT_WINDOW_DAYS)

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.param("start") in {first_window.isoformat(), second_window.isoformat()}:
                return _page(_rows(2))
            return ScriptedResponse(status=500, body=b"boom")

        result = _driver().run("max_ad_revenue", respond)

        assert isinstance(result.raised, AppLovinAPIError)
        assert result.saved_states
        assert result.final_state == AppLovinResumeConfig(next_window_start=second_window.isoformat())


class TestPagination:
    def test_full_page_advances_offset_and_short_page_ends_the_window(self) -> None:
        result = _driver().run(
            "max_ad_revenue",
            [
                _page(_rows(REPORT_PAGE_SIZE)),
                _page(_rows(REPORT_PAGE_SIZE)),
                _page(_rows(3)),
                *[_page([]) for _ in range(6)],
            ],
        )

        assert result.raised is None
        assert result.params("offset")[:4] == ["0", str(REPORT_PAGE_SIZE), str(REPORT_PAGE_SIZE * 2), "0"]
        # The empty later windows yield nothing, so only the three real pages come through.
        assert [len(batch) for batch in result.items] == [REPORT_PAGE_SIZE, REPORT_PAGE_SIZE, 3]
        # Mid-window checkpoints carry the offset; the window rollover resets it.
        assert (result.saved_states[0].next_window_start, result.saved_states[0].next_offset) == (
            _earliest().isoformat(),
            REPORT_PAGE_SIZE,
        )
        assert result.saved_states[2].next_offset == 0

    def test_resumes_from_saved_window_and_offset(self) -> None:
        resume_start = _today() - timedelta(days=1)
        result = _driver().run(
            "max_ad_revenue",
            [_page([])],
            resume_state=AppLovinResumeConfig(next_window_start=resume_start.isoformat(), next_offset=REPORT_PAGE_SIZE),
        )

        assert result.raised is None
        assert result.requests[0].param("start") == resume_start.isoformat()
        assert result.requests[0].param("offset") == str(REPORT_PAGE_SIZE)
        # A single window remains, so nothing older gets re-walked.
        assert len(result.requests) == 1

    def test_resume_state_behind_the_incremental_start_is_ignored(self) -> None:
        watermark = _today()
        expected_start = watermark - timedelta(days=REPORT_LOOKBACK_DAYS)
        result = _driver().run(
            "max_ad_revenue",
            [_page([]), _page([])],
            resume_state=AppLovinResumeConfig(next_window_start=(expected_start - timedelta(days=10)).isoformat()),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark.isoformat(),
        )

        assert result.raised is None
        assert result.requests[0].param("start") == expected_start.isoformat()

    def test_non_dict_results_are_dropped(self) -> None:
        result = _driver().run(
            "max_ad_revenue",
            [_page([{"day": "2026-07-01"}, "junk", None]), *[_page(None) for _ in range(6)]],
        )

        assert result.raised is None
        assert result.items == [[{"day": "2026-07-01"}]]


class TestErrorClassification:
    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_statuses_raise_the_auth_prefix(self, status_code: int) -> None:
        result = _driver().run("max_ad_revenue", [ScriptedResponse(status=status_code, body=b"Authentication Failed")])

        assert isinstance(result.raised, AppLovinAPIError)
        assert str(result.raised).startswith(AUTH_ERROR_PREFIX)

    @pytest.mark.parametrize("status_code", [400, 404, 422])
    def test_other_client_errors_raise_the_bad_request_prefix(self, status_code: int) -> None:
        result = _driver().run("max_ad_revenue", [ScriptedResponse(status=status_code, body=b"Invalid column")])

        assert isinstance(result.raised, AppLovinAPIError)
        assert str(result.raised).startswith(BAD_REQUEST_ERROR_PREFIX)
        assert "Invalid column" in str(result.raised)

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    def test_throttling_and_upstream_failures_stay_retryable(self, status_code: int) -> None:
        result = _driver().run("max_ad_revenue", always(ScriptedResponse(status=status_code, body=b"try later")))

        assert isinstance(result.raised, AppLovinAPIError)
        # Must not be classified as a permanent rejection, or an outage disables the source.
        assert str(result.raised).startswith(TRANSIENT_ERROR_PREFIX)

    def test_non_json_body_on_a_200_is_a_bad_request(self) -> None:
        result = _driver().run("max_ad_revenue", [ScriptedResponse(body=b"<html>oops</html>")])

        assert isinstance(result.raised, AppLovinAPIError)
        assert str(result.raised).startswith(BAD_REQUEST_ERROR_PREFIX)

    @pytest.mark.parametrize(
        "body_code, expected_prefix",
        [
            (401, AUTH_ERROR_PREFIX),
            (403, AUTH_ERROR_PREFIX),
            (400, BAD_REQUEST_ERROR_PREFIX),
            (429, TRANSIENT_ERROR_PREFIX),
            (500, TRANSIENT_ERROR_PREFIX),
        ],
    )
    def test_body_level_error_code_on_a_200_is_classified(self, body_code: int, expected_prefix: str) -> None:
        result = _driver().run("max_ad_revenue", [ScriptedResponse(json={"code": body_code, "results": []})])

        assert isinstance(result.raised, AppLovinAPIError)
        assert str(result.raised).startswith(expected_prefix)

    # A Report Key with reserved characters is percent-/plus-encoded in the request URL, so a
    # transport error that quotes the URL never carries the raw key — redaction must cover the
    # encoded forms too.
    @pytest.mark.parametrize("api_key", ["super-secret", "ab/c+d=="])
    def test_transport_error_never_leaks_the_report_key(self, api_key: str) -> None:
        # `requests`/`urllib3` quote the built URL, where the key is URL-encoded.
        leaked_url = f"/maxReport?api_key={quote_plus(api_key)}&columns=day"

        def fail_request(_request: RecordedRequest) -> ScriptedResponse:
            raise requests.ConnectionError(f"Max retries exceeded with url: {leaked_url}")

        result = _driver(api_key).run("max_ad_revenue", fail_request)

        assert isinstance(result.raised, AppLovinAPIError)
        message = str(result.raised)
        assert api_key not in message
        assert quote_plus(api_key) not in message
        assert quote(api_key, safe="") not in message
        assert "REDACTED" in message
        # The original exception carries the unredacted URL, so it must not be chained.
        assert result.raised.__cause__ is None

    @pytest.mark.parametrize("api_key", ["super-secret", "ab/c+d=="])
    def test_error_body_echoing_the_report_key_is_redacted(self, api_key: str) -> None:
        result = _driver(api_key).run(
            "max_ad_revenue", [ScriptedResponse(status=400, body=f"bad request for api_key={api_key}".encode())]
        )

        assert isinstance(result.raised, AppLovinAPIError)
        assert api_key not in str(result.raised)


class TestValidateCredentials:
    def test_advertiser_only_key_accepted_on_the_report_probe(self) -> None:
        with scripted_network([ScriptedResponse(status=403, body=b"Authentication Failed"), _page([])]) as network:
            assert validate_credentials("key") is True

        assert [request.path for request in network.requests_log] == ["/maxReport", "/report"]

    @pytest.mark.parametrize(
        "responses",
        [
            [ScriptedResponse(status=403, body=b"Authentication Failed")] * 2,
            [ScriptedResponse(json={"code": 403, "results": []})] * 2,
            [ScriptedResponse(body=b"Authentication Failed")] * 2,
        ],
    )
    def test_rejected_key_is_invalid(self, responses: list[ScriptedResponse]) -> None:
        with scripted_network(responses) as network:
            assert validate_credentials("bad") is False

        assert [request.path for request in network.requests_log] == ["/maxReport", "/report"]


class TestSourceResponse:
    def test_items_yields_rows_as_returned_by_the_api(self) -> None:
        rows = [{"day": "2026-07-01", "estimated_revenue": "1.23"}]
        result = _driver().run("max_ad_revenue", [_page(rows), *[_page([]) for _ in range(6)]])

        assert result.raised is None
        assert result.items == [rows]


class TestEndpointCatalogInvariants:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_primary_keys_are_requested_dimensions(self, endpoint: str) -> None:
        config = APPLOVIN_ENDPOINTS[endpoint]
        # A key column absent from `columns` would never appear in a row, so every merge
        # would multi-match and duplicate.
        assert set(config.primary_keys) <= set(config.dimensions)
        assert config.primary_keys

    @pytest.mark.parametrize("endpoint", ["max_ad_revenue", "max_ad_unit_revenue"])
    def test_max_report_network_and_request_metrics_are_mutually_exclusive(self, endpoint: str) -> None:
        config = APPLOVIN_ENDPOINTS[endpoint]
        # AppLovin refuses `requests` whenever `network`/`network_placement` is requested, and
        # only reports `attempts`/`responses`/`fill_rate` when one of them is.
        network_grain = "network" in config.dimensions
        assert ("requests" in config.metrics) is not network_grain
        for metric in ("attempts", "responses", "fill_rate"):
            assert (metric in config.metrics) is network_grain

    def test_lookback_covers_a_whole_window(self) -> None:
        # A mid-window crash is only self-healing when the next run re-reads the full window.
        assert REPORT_LOOKBACK_DAYS >= REPORT_WINDOW_DAYS
        assert REPORT_WINDOW_DAYS < MAX_REQUEST_WINDOW_DAYS
