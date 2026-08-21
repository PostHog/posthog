from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.applovin import (
    AUTH_ERROR_PREFIX,
    BAD_REQUEST_ERROR_PREFIX,
    TRANSIENT_ERROR_PREFIX,
    AppLovinAPIError,
    AppLovinResumeConfig,
    _body_code,
    _to_date,
    applovin_source,
    get_rows,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.applovin.applovin"


class FakeResumeManager(ResumableSourceManager[AppLovinResumeConfig]):
    """In-memory stand-in for the Redis-backed manager."""

    def __init__(self, state: Optional[AppLovinResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[AppLovinResumeConfig] = []
        self.clear_count = 0

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[AppLovinResumeConfig]:
        return self.state

    def save_state(self, data: AppLovinResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.clear_count += 1


def _response(body: Any = None, status_code: int = 200, text: str = "", json_error: bool = False) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.text = text
    if json_error:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = body
    return resp


def _rows(count: int) -> list[dict[str, str]]:
    return [{"day": "2026-07-01", "package_name": f"com.app.{index}"} for index in range(count)]


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def _urls(session: mock.MagicMock) -> list[str]:
    return [call.args[0] for call in session.return_value.get.call_args_list]


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
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_report_key_is_registered_for_redaction(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"code": 200, "results": []})

        list(get_rows("secret-key", "max_ad_revenue", mock.MagicMock(), FakeResumeManager()))

        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_every_endpoint_requests_its_declared_columns(self, mock_session: mock.MagicMock, endpoint: str) -> None:
        mock_session.return_value.get.return_value = _response({"code": 200, "results": []})
        config = APPLOVIN_ENDPOINTS[endpoint]

        list(get_rows("key", endpoint, mock.MagicMock(), FakeResumeManager()))

        url = _urls(mock_session)[0]
        assert urlparse(url).path == config.path
        params = _query(url)
        assert params["columns"] == [",".join(config.columns)]
        assert params["format"] == ["json"]
        assert params["api_key"] == ["key"]
        assert params["limit"] == [str(REPORT_PAGE_SIZE)]
        assert params["offset"] == ["0"]
        # Pinned so limit/offset paging can't reshuffle rows and `sort_mode="asc"` holds.
        assert params["sort_day"] == ["ASC"]
        for name, value in config.extra_params.items():
            assert params[name] == [value]


class TestWindowWalking:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_covers_the_whole_request_window_oldest_first(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"code": 200, "results": _rows(2)})
        manager = FakeResumeManager()

        batches = list(get_rows("key", "max_ad_revenue", mock.MagicMock(), manager))

        starts = [_query(url)["start"][0] for url in _urls(mock_session)]
        ends = [_query(url)["end"][0] for url in _urls(mock_session)]
        assert starts == sorted(starts)
        assert starts[0] == _earliest().isoformat()
        assert ends[-1] == _today().isoformat()
        # Windows tile the range with no gaps.
        for previous_end, next_start in zip(ends, starts[1:]):
            assert date.fromisoformat(next_start) == date.fromisoformat(previous_end) + timedelta(days=1)
        assert len(batches) == len(starts)
        assert [saved.next_window_start for saved in manager.saved] == starts[1:]
        # A completed walk leaves no checkpoint behind.
        assert manager.clear_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_checkpoint_survives_a_failed_walk(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = [
            _response({"code": 200, "results": _rows(2)}),
            _response(status_code=500, text="boom"),
        ]
        manager = FakeResumeManager()

        with pytest.raises(AppLovinAPIError):
            list(get_rows("key", "max_ad_revenue", mock.MagicMock(), manager))

        assert manager.saved
        assert manager.clear_count == 0

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_starts_a_lookback_before_the_watermark(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"code": 200, "results": []})
        watermark = _today() - timedelta(days=3)

        list(
            get_rows(
                "key",
                "publisher_report",
                mock.MagicMock(),
                FakeResumeManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark.isoformat(),
            )
        )

        expected = (watermark - timedelta(days=REPORT_LOOKBACK_DAYS)).isoformat()
        assert _query(_urls(mock_session)[0])["start"] == [expected]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_watermark_older_than_the_request_window_is_clamped(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"code": 200, "results": []})

        list(
            get_rows(
                "key",
                "publisher_report",
                mock.MagicMock(),
                FakeResumeManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=(_today() - timedelta(days=400)).isoformat(),
            )
        )

        # AppLovin errors on dates outside the window, so the stale watermark must not be sent.
        assert _query(_urls(mock_session)[0])["start"] == [_earliest().isoformat()]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_unparseable_watermark_falls_back_to_full_window(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"code": 200, "results": []})

        list(
            get_rows(
                "key",
                "publisher_report",
                mock.MagicMock(),
                FakeResumeManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="not-a-date",
            )
        )

        assert _query(_urls(mock_session)[0])["start"] == [_earliest().isoformat()]


class TestPagination:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_page_advances_offset_and_short_page_ends_the_window(self, mock_session: mock.MagicMock) -> None:
        first_window = [
            _response({"code": 200, "results": _rows(REPORT_PAGE_SIZE)}),
            _response({"code": 200, "results": _rows(REPORT_PAGE_SIZE)}),
            _response({"code": 200, "results": _rows(3)}),
        ]
        # Every later window returns a single short page.
        mock_session.return_value.get.side_effect = [
            *first_window,
            *[_response({"code": 200, "results": []}) for _ in range(50)],
        ]
        manager = FakeResumeManager()

        batches = list(get_rows("key", "max_ad_revenue", mock.MagicMock(), manager))

        offsets = [_query(url)["offset"][0] for url in _urls(mock_session)[:4]]
        assert offsets == ["0", str(REPORT_PAGE_SIZE), str(REPORT_PAGE_SIZE * 2), "0"]
        # The empty later windows yield nothing, so only the three real pages come through.
        assert [len(batch) for batch in batches] == [REPORT_PAGE_SIZE, REPORT_PAGE_SIZE, 3]
        # Mid-window checkpoints carry the offset; the window rollover resets it.
        assert (manager.saved[0].next_window_start, manager.saved[0].next_offset) == (
            _earliest().isoformat(),
            REPORT_PAGE_SIZE,
        )
        assert manager.saved[2].next_offset == 0

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_window_and_offset(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"code": 200, "results": []})
        resume_start = _today() - timedelta(days=1)
        manager = FakeResumeManager(
            AppLovinResumeConfig(next_window_start=resume_start.isoformat(), next_offset=REPORT_PAGE_SIZE)
        )

        list(get_rows("key", "max_ad_revenue", mock.MagicMock(), manager))

        params = _query(_urls(mock_session)[0])
        assert params["start"] == [resume_start.isoformat()]
        assert params["offset"] == [str(REPORT_PAGE_SIZE)]
        # A single window remains, so nothing older gets re-walked.
        assert len(_urls(mock_session)) == 1

    @pytest.mark.parametrize(
        "resume_start_offset_days, description",
        [
            (400, "older than the request window"),
            (-5, "in the future"),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_out_of_range_resume_state_is_ignored(
        self, mock_session: mock.MagicMock, resume_start_offset_days: int, description: str
    ) -> None:
        mock_session.return_value.get.return_value = _response({"code": 200, "results": []})
        resume_start = _today() - timedelta(days=resume_start_offset_days)
        manager = FakeResumeManager(AppLovinResumeConfig(next_window_start=resume_start.isoformat()))

        list(get_rows("key", "max_ad_revenue", mock.MagicMock(), manager))

        assert _query(_urls(mock_session)[0])["start"] == [_earliest().isoformat()]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_state_behind_the_incremental_start_is_ignored(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"code": 200, "results": []})
        watermark = _today()
        expected_start = watermark - timedelta(days=REPORT_LOOKBACK_DAYS)
        manager = FakeResumeManager(
            AppLovinResumeConfig(next_window_start=(expected_start - timedelta(days=10)).isoformat())
        )

        list(
            get_rows(
                "key",
                "max_ad_revenue",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark.isoformat(),
            )
        )

        assert _query(_urls(mock_session)[0])["start"] == [expected_start.isoformat()]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_dict_results_are_dropped(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = [
            _response({"code": 200, "results": [{"day": "2026-07-01"}, "junk", None]}),
            *[_response({"code": 200, "results": None}) for _ in range(50)],
        ]

        batches = list(get_rows("key", "max_ad_revenue", mock.MagicMock(), FakeResumeManager()))

        assert batches == [[{"day": "2026-07-01"}]]


class TestErrorClassification:
    @pytest.mark.parametrize("status_code", [401, 403])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_auth_statuses_raise_the_auth_prefix(self, mock_session: mock.MagicMock, status_code: int) -> None:
        mock_session.return_value.get.return_value = _response(status_code=status_code, text="Authentication Failed")

        with pytest.raises(AppLovinAPIError) as exc_info:
            list(get_rows("key", "max_ad_revenue", mock.MagicMock(), FakeResumeManager()))

        assert str(exc_info.value).startswith(AUTH_ERROR_PREFIX)

    @pytest.mark.parametrize("status_code", [400, 404, 422])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_other_client_errors_raise_the_bad_request_prefix(
        self, mock_session: mock.MagicMock, status_code: int
    ) -> None:
        mock_session.return_value.get.return_value = _response(status_code=status_code, text="Invalid column")

        with pytest.raises(AppLovinAPIError) as exc_info:
            list(get_rows("key", "max_ad_revenue", mock.MagicMock(), FakeResumeManager()))

        assert str(exc_info.value).startswith(BAD_REQUEST_ERROR_PREFIX)
        assert "Invalid column" in str(exc_info.value)

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_throttling_and_upstream_failures_stay_retryable(
        self, mock_session: mock.MagicMock, status_code: int
    ) -> None:
        mock_session.return_value.get.return_value = _response(status_code=status_code, text="try later")

        with pytest.raises(AppLovinAPIError) as exc_info:
            list(get_rows("key", "max_ad_revenue", mock.MagicMock(), FakeResumeManager()))

        # Must not be classified as a permanent rejection, or an outage disables the source.
        assert str(exc_info.value).startswith(TRANSIENT_ERROR_PREFIX)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_json_body_on_a_200_is_a_bad_request(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response(text="<html>oops</html>", json_error=True)

        with pytest.raises(AppLovinAPIError) as exc_info:
            list(get_rows("key", "max_ad_revenue", mock.MagicMock(), FakeResumeManager()))

        assert str(exc_info.value).startswith(BAD_REQUEST_ERROR_PREFIX)

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
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_body_level_error_code_on_a_200_is_classified(
        self, mock_session: mock.MagicMock, body_code: int, expected_prefix: str
    ) -> None:
        mock_session.return_value.get.return_value = _response({"code": body_code, "results": []})

        with pytest.raises(AppLovinAPIError) as exc_info:
            list(get_rows("key", "max_ad_revenue", mock.MagicMock(), FakeResumeManager()))

        assert str(exc_info.value).startswith(expected_prefix)

    # A Report Key with reserved characters is percent-/plus-encoded in the request URL, so a
    # transport error that quotes the URL never carries the raw key — redaction must cover the
    # encoded forms too.
    @pytest.mark.parametrize("api_key", ["super-secret", "ab/c+d=="])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_transport_error_never_leaks_the_report_key(self, mock_session: mock.MagicMock, api_key: str) -> None:
        # `requests`/`urllib3` quote the built URL, where the key is URL-encoded.
        leaked_url = f"/maxReport?api_key={quote_plus(api_key)}&columns=day"
        mock_session.return_value.get.side_effect = requests.ConnectionError(
            f"Max retries exceeded with url: {leaked_url}"
        )

        with pytest.raises(AppLovinAPIError) as exc_info:
            list(get_rows(api_key, "max_ad_revenue", mock.MagicMock(), FakeResumeManager()))

        message = str(exc_info.value)
        assert api_key not in message
        assert quote_plus(api_key) not in message
        assert quote(api_key, safe="") not in message
        assert "REDACTED" in message
        # The original exception carries the unredacted URL, so it must not be chained.
        assert exc_info.value.__cause__ is None

    @pytest.mark.parametrize("api_key", ["super-secret", "ab/c+d=="])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_error_body_echoing_the_report_key_is_redacted(self, mock_session: mock.MagicMock, api_key: str) -> None:
        mock_session.return_value.get.return_value = _response(
            status_code=400, text=f"bad request for api_key={api_key}"
        )

        with pytest.raises(AppLovinAPIError) as exc_info:
            list(get_rows(api_key, "max_ad_revenue", mock.MagicMock(), FakeResumeManager()))

        assert api_key not in str(exc_info.value)


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_key_accepted_on_the_first_probe(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"code": 200, "results": []})

        assert validate_credentials("key") is True
        assert len(_urls(mock_session)) == 1
        assert urlparse(_urls(mock_session)[0]).path == "/maxReport"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_advertiser_only_key_accepted_on_the_report_probe(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = [
            _response(status_code=403, text="Authentication Failed"),
            _response({"code": 200, "results": []}),
        ]

        assert validate_credentials("key") is True
        assert [urlparse(url).path for url in _urls(mock_session)] == ["/maxReport", "/report"]

    @pytest.mark.parametrize(
        "responses",
        [
            [_response(status_code=403, text="Authentication Failed")] * 2,
            [_response({"code": 403, "results": []})] * 2,
            [_response(text="Authentication Failed", json_error=True)] * 2,
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rejected_key_is_invalid(self, mock_session: mock.MagicMock, responses: list[mock.MagicMock]) -> None:
        mock_session.return_value.get.side_effect = responses

        assert validate_credentials("bad") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_transport_failure_is_not_validated_and_does_not_raise(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        assert validate_credentials("key") is False


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        response = applovin_source("key", endpoint, mock.MagicMock(), FakeResumeManager())

        assert response.name == endpoint
        assert response.primary_keys == APPLOVIN_ENDPOINTS[endpoint].primary_keys
        assert response.sort_mode == "asc"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_items_yields_rows_as_returned_by_the_api(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = [
            _response({"code": 200, "results": [{"day": "2026-07-01", "estimated_revenue": "1.23"}]}),
            *[_response({"code": 200, "results": []}) for _ in range(50)],
        ]
        response = applovin_source("key", "max_ad_revenue", mock.MagicMock(), FakeResumeManager())

        batches = list(cast("Iterable[Any]", response.items()))

        assert batches == [[{"day": "2026-07-01", "estimated_revenue": "1.23"}]]


class TestEndpointCatalogInvariants:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_primary_keys_are_requested_dimensions(self, endpoint: str) -> None:
        config = APPLOVIN_ENDPOINTS[endpoint]
        # A key column absent from `columns` would never appear in a row, so every merge
        # would multi-match and duplicate.
        assert set(config.primary_keys) <= set(config.dimensions)
        assert config.primary_keys

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_day_is_always_requested_and_keyed(self, endpoint: str) -> None:
        config = APPLOVIN_ENDPOINTS[endpoint]
        assert "day" in config.dimensions
        assert "day" in config.primary_keys

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_columns_have_no_duplicates(self, endpoint: str) -> None:
        columns = APPLOVIN_ENDPOINTS[endpoint].columns
        assert len(columns) == len(set(columns))

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
