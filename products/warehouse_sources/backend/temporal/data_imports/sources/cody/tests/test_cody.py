import io
from collections.abc import Iterable, Iterator
from datetime import date
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from freezegun import freeze_time
from unittest import mock

import urllib3
import requests
from parameterized import parameterized
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cody import cody
from products.warehouse_sources.backend.temporal.data_imports.sources.cody.cody import (
    CodyCredentialsError,
    CodyResumeConfig,
    CodyRetryableError,
    _month_windows,
    _parse_csv_rows,
    _rows_from_response,
    cody_source,
    normalize_instance_url,
    validate_credentials,
)

CSV_BODY = "User Email,Chats,Completion Acceptance Rate (CAR%)\na@b.com,12,0.5\nc@d.com,3,0.25\n"


@pytest.fixture(autouse=True)
def _instant_retries():
    fetch: Any = cody._fetch  # the tenacity wrapper's `retry` attribute isn't in the Callable type
    original_wait = fetch.retry.wait
    fetch.retry.wait = wait_none()
    yield
    fetch.retry.wait = original_wait


def _response(
    status_code: int = 200,
    text: str = "",
    content_type: str = "text/csv",
    json_data: Any = None,
) -> requests.Response:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    response.ok = status_code < 400
    response.text = text
    response.headers = {"Content-Type": content_type}
    response.json.return_value = json_data
    # The CSV path stream-parses `response.raw`; a real urllib3 response over the body keeps
    # the `decode_content` + TextIOWrapper plumbing honest.
    response.raw = urllib3.response.HTTPResponse(body=io.BytesIO(text.encode("utf-8")), preload_content=False)
    typed = cast(requests.Response, response)
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: Error for url: {cody.CODY_BASE_URL}/x", response=typed
        )
    return typed


def _manager(resume_state: CodyResumeConfig | None = None) -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _batches(source: SourceResponse) -> Iterator[list[dict[str, Any]]]:
    return iter(cast(Iterable[list[dict[str, Any]]], source.items()))


def _requested_urls(session: mock.Mock) -> list[str]:
    return [call.args[0] for call in session.get.call_args_list]


class TestCodyTransport:
    @parameterized.expand(
        [
            # (start, today, expected inclusive windows)
            (date(2023, 1, 1), date(2023, 1, 15), [(date(2023, 1, 1), date(2023, 1, 15))]),
            (date(2023, 1, 1), date(2023, 1, 31), [(date(2023, 1, 1), date(2023, 1, 31))]),
            (
                date(2023, 1, 1),
                date(2023, 3, 2),
                [
                    (date(2023, 1, 1), date(2023, 1, 31)),
                    (date(2023, 2, 1), date(2023, 2, 28)),
                    (date(2023, 3, 1), date(2023, 3, 2)),
                ],
            ),
            (
                date(2023, 12, 1),
                date(2024, 1, 5),
                [(date(2023, 12, 1), date(2023, 12, 31)), (date(2024, 1, 1), date(2024, 1, 5))],
            ),
        ]
    )
    def test_month_windows_cover_range_without_gaps(self, start, today, expected):
        windows = list(_month_windows(start, today))

        assert windows == expected
        for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
            assert (next_start - prev_end).days == 1  # inclusive bounds — no gap, no overlap

    @parameterized.expand(
        [
            ("example.sourcegraphcloud.com", "example.sourcegraphcloud.com"),
            ("https://example.sourcegraphcloud.com", "example.sourcegraphcloud.com"),
            ("https://example.sourcegraphcloud.com/", "example.sourcegraphcloud.com"),
            ("http://example.com/some/path", "example.com"),
            ("  example.com  ", "example.com"),
        ]
    )
    def test_normalize_instance_url_strips_scheme_and_path(self, raw, expected):
        assert normalize_instance_url(raw) == expected

    def test_parse_csv_rows_normalizes_headers(self):
        rows = list(_parse_csv_rows(io.StringIO(CSV_BODY)))

        assert rows == [
            {"user_email": "a@b.com", "chats": "12", "completion_acceptance_rate_car": "0.5"},
            {"user_email": "c@d.com", "chats": "3", "completion_acceptance_rate_car": "0.25"},
        ]

    def test_parse_csv_rows_skips_malformed_and_blank_rows(self):
        # A short row zipped against the headers would silently drop trailing columns for
        # that row — it must be skipped, not half-parsed.
        text = "a,b\n1\n\n2,3\n"
        logger = mock.Mock()

        rows = list(_parse_csv_rows(io.StringIO(text), logger))

        assert rows == [{"a": "2", "b": "3"}]
        logger.warning.assert_called_once()

    @parameterized.expand(
        [
            # The credits endpoint's format isn't documented — both JSON shapes and CSV must parse.
            ("application/json", None, [{"id": "b1"}, {"id": "b2"}], [{"id": "b1"}, {"id": "b2"}]),
            ("application/json; charset=utf-8", None, {"buckets": [{"id": "b1"}]}, [{"id": "b1"}]),
            ("application/json", None, {"id": "b1"}, [{"id": "b1"}]),
            ("text/csv", "id,amount\nb1,10\n", None, [{"id": "b1", "amount": "10"}]),
        ]
    )
    def test_rows_from_response_sniffs_json_and_csv(self, content_type, text, json_data, expected):
        response = _response(200, text=text or "", content_type=content_type, json_data=json_data)

        assert list(_rows_from_response(response, mock.Mock())) == expected

    def test_validate_credentials_probes_one_day_by_user_report(self):
        session = mock.Mock()
        session.get.return_value = _response(200, text=CSV_BODY)

        with (
            freeze_time("2025-06-15"),
            mock.patch.object(cody, "make_tracked_session", return_value=session),
        ):
            assert validate_credentials("token", "example.com") is True

        url = session.get.call_args.args[0]
        assert "granularity=by_user" in url
        assert "startDate=2025-06-15" in url and "endDate=2025-06-15" in url
        assert "instanceURL=example.com" in url
        # Probe must stream and never read the body — a large per-user report can't be buffered.
        assert session.get.call_args.kwargs["stream"] is True
        session.get.return_value.close.assert_called_once()

    @parameterized.expand([(401,), (403,), (404,), (400,)])
    def test_validate_credentials_raises_user_facing_error(self, status_code):
        session = mock.Mock()
        session.get.return_value = _response(status_code)

        with mock.patch.object(cody, "make_tracked_session", return_value=session):
            with pytest.raises(CodyCredentialsError):
                validate_credentials("token", "example.com")

    @parameterized.expand([(429,), (500,), (503,)])
    def test_validate_credentials_raises_retryable_on_transient_status(self, status_code):
        # A rate limit or 5xx must not be conflated with a bad credential.
        session = mock.Mock()
        session.get.return_value = _response(status_code)

        with mock.patch.object(cody, "make_tracked_session", return_value=session):
            with pytest.raises(CodyRetryableError):
                validate_credentials("token", "example.com")

    def test_session_masks_token_and_sends_bearer_auth(self):
        # The tracked transport logs and samples requests; without redaction the raw token
        # would leak into HTTP telemetry.
        with mock.patch.object(cody, "make_tracked_session") as make_session:
            cody._make_session("sgat_token")

        kwargs = make_session.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == "Bearer sgat_token"
        assert "sgat_token" in kwargs["redact_values"]
        assert kwargs["allow_redirects"] is False

    @parameterized.expand([(429,), (500,), (503,)])
    def test_fetch_retries_transient_errors(self, status_code):
        session = mock.Mock()
        session.get.side_effect = [_response(status_code), _response(200, text=CSV_BODY)]

        result = cody._fetch(session, f"{cody.CODY_BASE_URL}/api/credits", mock.Mock())

        assert result.status_code == 200
        assert session.get.call_count == 2

    def test_fetch_raises_on_client_error_without_retry(self):
        session = mock.Mock()
        session.get.return_value = _response(401)

        with pytest.raises(requests.HTTPError):
            cody._fetch(session, f"{cody.CODY_BASE_URL}/api/credits", mock.Mock())

        assert session.get.call_count == 1

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown Cody endpoint"):
            cody_source("token", "example.com", "audit_logs", mock.Mock(), _manager())

    @parameterized.expand([(endpoint,) for endpoint in cody.CODY_ENDPOINTS])
    def test_source_response_shape(self, endpoint):
        response = cody_source("token", "example.com", endpoint, mock.Mock(), _manager())

        assert response.name == endpoint
        assert response.primary_keys is None
        assert response.sort_mode == "asc"

    @parameterized.expand(
        [
            ("usage_by_user", "by_user"),
            ("usage_by_user_month", "by_user_month"),
        ]
    )
    def test_aggregate_reports_fetch_all_time_in_one_request(self, endpoint, granularity):
        # Windowing an aggregate report would change per-user totals to per-window totals,
        # so these must go out as a single request with no date bounds.
        manager = _manager()
        session = mock.Mock()
        session.get.return_value = _response(200, text=CSV_BODY)

        with mock.patch.object(cody, "make_tracked_session", return_value=session):
            batches = list(_batches(cody_source("token", "example.com", endpoint, mock.Mock(), manager)))

        assert [len(batch) for batch in batches] == [2]
        params = parse_qs(urlparse(session.get.call_args.args[0]).query)
        assert params == {"instanceURL": ["example.com"], "granularity": [granularity]}
        manager.save_state.assert_not_called()

    def test_credits_requests_without_granularity(self):
        session = mock.Mock()
        session.get.return_value = _response(200, text="id,amount\nb1,10\n")

        with mock.patch.object(cody, "make_tracked_session", return_value=session):
            batches = list(_batches(cody_source("token", "example.com", "credits", mock.Mock(), _manager())))

        assert batches == [[{"id": "b1", "amount": "10"}]]
        url = session.get.call_args.args[0]
        assert url.startswith(f"{cody.CODY_BASE_URL}/api/credits?")
        assert "granularity" not in url
        # Reports must stay streamed — buffering the whole body lets a huge report OOM the worker.
        assert session.get.call_args.kwargs["stream"] is True

    def test_windowed_endpoint_walks_months_from_origin_and_checkpoints(self):
        manager = _manager()
        session = mock.Mock()
        # A fresh response per window — each one's raw stream is consumed exactly once.
        session.get.side_effect = lambda *args, **kwargs: _response(200, text=CSV_BODY)

        with (
            freeze_time("2023-03-15"),
            mock.patch.object(cody, "make_tracked_session", return_value=session),
        ):
            batches = list(_batches(cody_source("token", "example.com", "usage_by_user_day", mock.Mock(), manager)))

        urls = _requested_urls(session)
        assert len(urls) == 3  # Jan, Feb, and the clipped March window
        assert "startDate=2023-01-01" in urls[0] and "endDate=2023-01-31" in urls[0]
        assert "startDate=2023-02-01" in urls[1] and "endDate=2023-02-28" in urls[1]
        assert "startDate=2023-03-01" in urls[2] and "endDate=2023-03-15" in urls[2]
        assert all("granularity=by_user_day" in url for url in urls)
        assert len(batches) == 3

        # A checkpoint lands after each fully-yielded window except the final one, and the
        # completed walk clears state so a same-job retry restarts from the origin.
        saved = [call.args[0].window_start for call in manager.save_state.call_args_list]
        assert saved == ["2023-02-01", "2023-03-01"]
        manager.clear_state.assert_called_once()

    def test_windowed_endpoint_resumes_from_saved_window(self):
        manager = _manager(CodyResumeConfig(window_start="2023-03-01"))
        session = mock.Mock()
        session.get.return_value = _response(200, text=CSV_BODY)

        with (
            freeze_time("2023-03-15"),
            mock.patch.object(cody, "make_tracked_session", return_value=session),
        ):
            list(_batches(cody_source("token", "example.com", "usage_by_user_day", mock.Mock(), manager)))

        urls = _requested_urls(session)
        assert len(urls) == 1  # earlier windows are not re-fetched
        assert "startDate=2023-03-01" in urls[0] and "endDate=2023-03-15" in urls[0]

    def test_windowed_endpoint_checkpoints_only_after_rows_are_consumed(self):
        manager = _manager()
        session = mock.Mock()
        session.get.side_effect = lambda *args, **kwargs: _response(200, text=CSV_BODY)

        with (
            freeze_time("2023-02-10"),
            mock.patch.object(cody, "make_tracked_session", return_value=session),
        ):
            iterator = _batches(cody_source("token", "example.com", "usage_by_user_day", mock.Mock(), manager))

            next(iterator)
            # The generator is suspended at the yield — nothing saved until the consumer has
            # taken the batch, so a crash mid-batch re-fetches the window instead of skipping it.
            assert manager.save_state.call_count == 0

            list(iterator)

        assert [call.args[0].window_start for call in manager.save_state.call_args_list] == ["2023-02-01"]
