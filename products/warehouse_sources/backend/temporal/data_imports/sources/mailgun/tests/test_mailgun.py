import time
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookCreationResult
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailgun import (
    MailgunSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun import mailgun as mailgun_module
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun import (
    EVENTS_CONSISTENCY_LAG_SECONDS,
    EVENTS_LOOKBACK_DAYS,
    INVALID_KEY_ERROR,
    LOGS_LOOKBACK_DAYS,
    METRICS_PAGE_SIZE,
    MailgunAllDomainsSkippedError,
    MailgunResumeConfig,
    MailgunRetryableError,
    _epoch_to_datetime,
    _initial_url,
    _normalize_row,
    _parse_retry_after,
    _to_epoch,
    _webhook_table_transformer,
    create_webhook,
    delete_webhook,
    get_domain_names,
    get_external_webhook_info,
    mailgun_source,
    sync_webhook_events,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.settings import (
    MAILGUN_ENDPOINTS,
    WEBHOOK_EVENTS_ENDPOINT,
    WEBHOOK_TYPES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.source import MailgunSource

US_BASE = "https://api.mailgun.net"
POSTHOG_URL = "https://us.posthog.com/public/webhooks/abc"


def _make_manager(resume_state: MailgunResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _driver() -> SourceDriver:
    return SourceDriver(MailgunSource(), MailgunSourceConfig(api_key="key", region="us"))


def _paging_page(items: list[dict[str, Any]], next_url: str | None) -> dict[str, Any]:
    paging: dict[str, Any] = {"first": "f", "last": "l"}
    if next_url is not None:
        paging["next"] = next_url
    return {"items": items, "paging": paging}


class TestHelpers:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            ("1700000000.5", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-number", None),
            (True, None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected

    @pytest.mark.parametrize(
        "value, expected",
        [
            (1521472262.908181, datetime.fromtimestamp(1521472262.908181, tz=UTC)),
            (1521472262, datetime.fromtimestamp(1521472262, tz=UTC)),
            (None, None),
            ("not-a-timestamp", "not-a-timestamp"),
            (True, True),
        ],
    )
    def test_epoch_to_datetime(self, value, expected):
        assert _epoch_to_datetime(value) == expected

    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            ("", None),
            ("30", 30.0),
            ("0", 0.0),
            ("-5", 0.0),
            ("garbage", None),
        ],
    )
    def test_parse_retry_after(self, value, expected):
        assert _parse_retry_after(value) == expected

    def test_parse_retry_after_http_date(self):
        retry_at = datetime.now(UTC) + timedelta(seconds=60)
        result = _parse_retry_after(retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT"))
        assert result is not None
        assert 0 < result <= 61


class TestInitialUrl:
    def test_domain_is_url_quoted_in_path(self):
        url = _initial_url(US_BASE, MAILGUN_ENDPOINTS["bounces"], "ex/ample.com")
        assert url is not None
        assert "/v3/ex%2Fample.com/bounces" in url

    def test_domain_scoped_endpoint_without_domain_raises(self):
        with pytest.raises(ValueError):
            _initial_url(US_BASE, MAILGUN_ENDPOINTS["events"], None)

    @pytest.mark.parametrize(
        "watermark_seconds_ago, expected_begin_seconds_ago",
        [
            (None, EVENTS_LOOKBACK_DAYS * 24 * 60 * 60),
            (3 * 60 * 60, 3 * 60 * 60),
        ],
    )
    def test_events_query_always_sends_an_ascending_time_range(self, watermark_seconds_ago, expected_begin_seconds_ago):
        now = 1_800_000_000
        begin = None if watermark_seconds_ago is None else now - watermark_seconds_ago
        with mock.patch.object(mailgun_module.time, "time", return_value=now):
            url = _initial_url(US_BASE, MAILGUN_ENDPOINTS["events"], "example.com", begin)

        assert url is not None
        query = parse_qs(urlparse(url).query)
        assert query["ascending"] == ["yes"]
        assert query["begin"] == [str(now - expected_begin_seconds_ago)]
        assert query["end"] == [str(now - EVENTS_CONSISTENCY_LAG_SECONDS)]


class TestNormalizeRow:
    def test_injects_domain_for_domain_scoped_endpoints(self):
        row = _normalize_row(MAILGUN_ENDPOINTS["bounces"], "example.com", {"address": "a@b.com"})
        assert row == {"address": "a@b.com", "domain": "example.com"}

    def test_does_not_mutate_original_item(self):
        item = {"id": "x", "timestamp": 1521472262.9}
        _normalize_row(MAILGUN_ENDPOINTS["events"], "example.com", item)
        assert item == {"id": "x", "timestamp": 1521472262.9}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (404, (False, INVALID_KEY_ERROR)),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code, expected):
        response = ScriptedResponse(status=status_code, json={})
        with scripted_network(always(response) if status_code >= 500 else [response]) as network:
            assert validate_credentials("key", "us") == expected
        assert network.requests_log[0].path == "/v4/domains"
        assert network.requests_log[0].param("limit") == "1"


class TestGetDomainNames:
    def test_collects_names_across_skip_pages(self):
        page_size = MAILGUN_ENDPOINTS["domains"].page_size
        full_page = {"items": [{"name": f"domain-{i}.com"} for i in range(page_size)]}
        partial_page = {"items": [{"name": "last.com"}]}
        with scripted_network([ScriptedResponse(json=full_page), ScriptedResponse(json=partial_page)]) as network:
            names = get_domain_names("key", US_BASE, mock.MagicMock())

        assert len(names) == page_size + 1
        assert names[-1] == "last.com"
        assert network.requests_log[1].param("skip") == str(page_size)


class TestGetRows:
    def test_domains_endpoint_uses_skip_pagination(self):
        page_size = MAILGUN_ENDPOINTS["domains"].page_size
        full_page = {"items": [{"id": f"id-{i}", "name": f"d{i}.com"} for i in range(page_size)]}
        partial_page = {"items": [{"id": "id-last", "name": "last.com"}]}
        result = _driver().run("domains", [ScriptedResponse(json=full_page), ScriptedResponse(json=partial_page)])

        assert result.raised is None
        assert len(result.rows) == page_size + 1
        assert result.params("skip") == ["0", str(page_size)]

    @pytest.mark.parametrize(
        "self_referencing, expected_requests, expected_rows",
        [(True, 2, 2), (False, 3, 4)],
    )
    def test_repeating_paging_cursor_terminates(self, self_referencing, expected_requests, expected_rows):
        # Mailgun's tags endpoint re-serves its terminal page behind a stable `page=next&tag=<last>`
        # cursor instead of returning an empty page. Unguarded, the chain re-yields the same rows
        # until the activity is killed, and every repeat is billed as a synced row. Two shapes: the
        # cursor pointing at the page it came from, and a two-URL cycle between pages.
        items = [{"tag": "t1"}, {"tag": "t2"}]
        page_a = f"{US_BASE}/v3/a.com/tags?limit=1000"
        page_b = f"{page_a}&page=next&tag=t2"
        next_of_a = page_a if self_referencing else page_b

        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v4/domains":
                return ScriptedResponse(json={"items": [{"name": "a.com"}]})
            return ScriptedResponse(json=_paging_page(items, next_of_a if request.url == page_a else page_a))

        result = _driver().run("tags", answer)

        assert result.raised is None
        assert len(result.requests) == expected_requests
        assert len(result.rows) == expected_rows

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.MAX_PAGES_PER_CHAIN", 3
    )
    def test_paging_stops_at_the_page_cap(self):
        # A cursor that mints a fresh URL for every page never repeats, so the seen-URL guard can't
        # see it and only the page cap ends the chain.
        pages_fetched = 0

        def answer(request: RecordedRequest) -> ScriptedResponse:
            nonlocal pages_fetched
            if request.path == "/v4/domains":
                return ScriptedResponse(json={"items": [{"name": "a.com"}]})
            pages_fetched += 1
            return ScriptedResponse(
                json=_paging_page(
                    [{"tag": f"t{pages_fetched}"}], f"{US_BASE}/v3/a.com/tags?page=next&tag=t{pages_fetched}"
                )
            )

        logger = mock.MagicMock()
        result = _driver().run("tags", answer, logger=logger)

        assert result.raised is None
        assert pages_fetched == 3
        assert len(result.rows) == 3
        assert "exceeded 3 pages" in logger.warning.call_args.args[0]

    def test_incremental_watermark_inside_lag_window_skips_fetch(self):
        domains_page = {"items": [{"name": "a.com"}, {"name": "b.com"}]}
        result = _driver().run(
            "events",
            [ScriptedResponse(json=domains_page)],
            db_incremental_field_last_value=int(time.time()),
            incremental_field="timestamp",
        )

        assert result.raised is None
        assert result.rows == []
        # Only the domain listing was fetched; both domains were skipped.
        assert result.paths == ["/v4/domains"]

    def test_resume_with_completed_state_yields_nothing(self):
        result = _driver().run("events", [], resume_state=MailgunResumeConfig())

        assert result.raised is None
        assert result.rows == []
        assert result.requests == []

    @pytest.mark.parametrize("status_code", [400, 401, 403])
    def test_domain_scoped_access_error_skips_domain_and_continues_fan_out(self, status_code):
        # The account lists a domain that can't be queried (disabled / unverified for 400, or a
        # domain the key has no access to for 401/403). It must skip that domain, not abort the
        # whole fan-out, so b.com still imports. A global credential failure 401s the /v4/domains
        # listing instead, which never reaches the fan-out and stays non-retryable.
        domains_page = {"items": [{"name": "a.com"}, {"name": "b.com"}]}
        b_events = _paging_page([{"id": "e2", "timestamp": 1700000100.5}], None)
        result = _driver().run(
            "events",
            [
                ScriptedResponse(json=domains_page),
                ScriptedResponse(status=status_code, json={}),
                ScriptedResponse(json=b_events),
            ],
        )

        assert result.raised is None
        assert [(row["id"], row["domain"]) for row in result.rows] == [("e2", "b.com")]
        # The skipped domain leaves no in-flight chain behind, and the fan-out completes cleanly.
        assert result.saved_states[0].current_domain is None
        assert result.saved_states[-1].next_url is None
        assert result.saved_states[-1].pending_domains == []

    def test_every_domain_skipped_fails_the_sync(self):
        domains_page = {"items": [{"name": "a.com"}, {"name": "b.com"}, {"name": "c.com"}]}
        result = _driver().run(
            "events",
            [
                ScriptedResponse(json=domains_page),
                ScriptedResponse(status=403, json={}),
                ScriptedResponse(status=400, json={}),
                ScriptedResponse(status=403, json={}),
            ],
        )

        assert isinstance(result.raised, MailgunAllDomainsSkippedError)
        assert "(400 on 1 domain, 403 on 2 domains)" in str(result.raised)

        # This message must stay a stable, non-sensitive substring of get_non_retryable_errors,
        # or an account with every domain rejected gets retried instead of surfaced to the user.
        non_retryable_errors = MailgunSource().get_non_retryable_errors()
        matches = [message for pattern, message in non_retryable_errors.items() if pattern in str(result.raised)]
        assert len(matches) == 1

    def test_domain_listing_401_still_raises(self):
        # A 401 on the /v4/domains listing is a global credential failure, not a single bad
        # domain — it must surface (and stay non-retryable) rather than be skipped per-domain.
        result = _driver().run("events", [ScriptedResponse(status=401, json={})])
        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error" in str(result.raised)

    def test_account_level_400_still_raises(self):
        # A 400 on a non-domain-scoped endpoint means our request is wrong, not a bad domain —
        # it must surface rather than be silently skipped.
        result = _driver().run("mailing_lists", [ScriptedResponse(status=400, json={})])
        assert isinstance(result.raised, requests.HTTPError)
        assert "400 Client Error" in str(result.raised)

    def test_domain_scoped_500_still_raises(self):
        # Server errors are transient and retryable — they must not be swallowed as a skip.
        domains_page = {"items": [{"name": "a.com"}]}

        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v4/domains":
                return ScriptedResponse(json=domains_page)
            return ScriptedResponse(status=500, json={})

        result = _driver().run("events", answer)
        assert isinstance(result.raised, MailgunRetryableError)
        assert set(result.paths) == {"/v4/domains", "/v3/a.com/events"}

    def test_non_ok_response_raises(self):
        result = _driver().run("mailing_lists", [ScriptedResponse(status=401, body=b"unauthorized")])
        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error" in str(result.raised)

    def test_retries_on_429_then_succeeds(self):
        result = _driver().run(
            "mailing_lists",
            [
                ScriptedResponse(status=429, json={}, headers={"Retry-After": "1"}),
                ScriptedResponse(json=_paging_page([{"address": "a@x.com"}], None)),
            ],
        )

        assert result.raised is None
        assert [row["address"] for row in result.rows] == ["a@x.com"]
        assert result.paths == ["/v3/lists/pages", "/v3/lists/pages"]

    @pytest.mark.parametrize(
        "headers, expected_retry_after",
        [({"Retry-After": "2"}, 2.0), ({"Retry-After": "999"}, 999.0), ({}, None)],
    )
    def test_a_rate_limit_that_persists_raises_the_retryable_error(self, headers, expected_retry_after):
        result = _driver().run("mailing_lists", always(ScriptedResponse(status=429, json={}, headers=headers)))

        assert isinstance(result.raised, MailgunRetryableError)
        assert result.raised.retry_after == expected_retry_after


def _metrics_item(day: date, tag: str) -> dict[str, Any]:
    return {
        "dimensions": [
            {"dimension": "time", "value": f"{day.strftime('%a, %d %b %Y')} 00:00:00 +0000", "display_value": ""},
            {"dimension": "tag", "value": tag, "display_value": tag.title()},
        ],
        "metrics": {"delivered_count": 3, "opened_rate": "66.67"},
    }


def _request_day(request: RecordedRequest) -> date:
    return datetime.strptime(request.json()["start"], "%a, %d %b %Y %H:%M:%S %z").date()


# Short enough for the driver's request limit; production walks a full year of days.
METRICS_LOOKBACK_DAYS = 20


class TestMetricsRows:
    @pytest.fixture(autouse=True)
    def _short_lookback(self):
        with mock.patch.object(mailgun_module, "METRICS_LOOKBACK_DAYS", METRICS_LOOKBACK_DAYS):
            yield

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(MailgunSource(), MailgunSourceConfig(api_key="key-123", region="us"))

    def test_walks_one_day_per_request_and_pages_within_a_busy_day(self):
        today = datetime.now(UTC).date()
        busy_day = today - timedelta(days=10)

        def respond(request: RecordedRequest) -> ScriptedResponse:
            body = request.json()
            if _request_day(request) != busy_day:
                return ScriptedResponse(json={"items": []})
            count = METRICS_PAGE_SIZE if body["pagination"]["skip"] == 0 else 2
            return ScriptedResponse(json={"items": [_metrics_item(busy_day, f"tag-{i}") for i in range(count)]})

        result = self._driver().run("tag_metrics", respond)

        assert result.raised is None
        assert {request.method for request in result.requests} == {"POST"}
        assert {request.path for request in result.requests} == {"/v1/analytics/metrics"}
        days = [_request_day(request) for request in result.requests]
        assert days[0] == today - timedelta(days=METRICS_LOOKBACK_DAYS - 1)
        assert days[-1] == today
        assert len(days) == METRICS_LOOKBACK_DAYS + 1
        busy_requests = [request.json() for request in result.requests if _request_day(request) == busy_day]
        assert [body["pagination"]["skip"] for body in busy_requests] == [0, METRICS_PAGE_SIZE]
        assert busy_requests[0]["dimensions"] == ["time", "tag"]
        assert busy_requests[0]["pagination"]["sort"] == "tag:asc"
        assert len(result.rows) == METRICS_PAGE_SIZE + 2
        assert result.rows[0] == {
            "delivered_count": 3,
            "opened_rate": "66.67",
            "time": datetime.combine(busy_day, datetime.min.time(), tzinfo=UTC),
            "tag": "tag-0",
            "tag_display_value": "Tag-0",
        }

    @pytest.mark.parametrize(
        "watermark_days_ago, expected_first_day_ago",
        [
            (5, 7),
            # A watermark older than the lookback starts at the lookback edge instead.
            (METRICS_LOOKBACK_DAYS + 30, METRICS_LOOKBACK_DAYS - 1),
        ],
    )
    def test_incremental_sync_starts_shortly_before_the_watermark(self, watermark_days_ago, expected_first_day_ago):
        today = datetime.now(UTC).date()
        watermark = datetime.combine(today - timedelta(days=watermark_days_ago), datetime.min.time(), tzinfo=UTC)

        result = self._driver().run(
            "metrics",
            lambda _request: ScriptedResponse(json={"items": []}),
            incremental_field="time",
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        days = [_request_day(request) for request in result.requests]
        assert days[0] == today - timedelta(days=expected_first_day_ago)
        assert days[-1] == today
        assert result.requests[0].json()["dimensions"] == ["time"]

    def test_a_day_that_never_stops_returning_full_pages_moves_on_at_the_row_cap(self):
        today = datetime.now(UTC).date()
        full_page = ScriptedResponse(
            json={"items": [_metrics_item(today, f"tag-{i}") for i in range(METRICS_PAGE_SIZE)]}
        )

        with mock.patch.object(mailgun_module, "MAX_METRICS_ROWS_PER_DAY", METRICS_PAGE_SIZE):
            result = self._driver().run("tag_metrics", lambda _request: full_page)

        assert result.raised is None
        assert len(result.requests) == METRICS_LOOKBACK_DAYS
        assert {request.json()["pagination"]["skip"] for request in result.requests} == {0}

    def test_resume_continues_from_the_saved_day_and_offset(self):
        today = datetime.now(UTC).date()

        result = self._driver().run(
            "domain_metrics",
            lambda _request: ScriptedResponse(json={"items": []}),
            resume_state=MailgunResumeConfig(metrics_day=today.isoformat(), metrics_skip=METRICS_PAGE_SIZE),
        )

        assert result.raised is None
        assert len(result.requests) == 1
        assert _request_day(result.requests[0]) == today
        assert result.requests[0].json()["pagination"]["skip"] == METRICS_PAGE_SIZE


def _log_item(event_id: str) -> dict[str, Any]:
    return {"id": event_id, "event": "delivered", "@timestamp": "2024-07-08T12:30:00.250Z", "domain": {"name": "a.com"}}


class TestLogsRows:
    def test_follows_page_tokens_until_an_empty_page(self):
        pages = {
            None: {"items": [_log_item("e1"), _log_item("e2")], "pagination": {"next": "t1"}},
            "t1": {"items": [_log_item("e3")], "pagination": {"next": "t2"}},
            "t2": {"items": [], "pagination": {"next": "t3"}},
        }

        result = _driver().run(
            "logs", lambda request: ScriptedResponse(json=pages[request.json()["pagination"].get("token")])
        )

        assert result.raised is None
        assert {request.path for request in result.requests} == {"/v1/analytics/logs"}
        bodies = [request.json() for request in result.requests]
        assert [body["pagination"].get("token") for body in bodies] == [None, "t1", "t2"]
        assert {(body["start"], body["end"]) for body in bodies} == {(bodies[0]["start"], bodies[0]["end"])}
        # Mailgun's Logs API rejects a request missing `duration` with a 400, even though an
        # empty value has no effect on the explicit `start`/`end` window.
        assert {body["duration"] for body in bodies} == {""}
        assert {body["pagination"]["sort"] for body in bodies} == {"timestamp:asc"}
        assert [row["id"] for row in result.rows] == ["e1", "e2", "e3"]
        assert "@timestamp" not in result.rows[0]
        assert result.rows[0]["timestamp"] == datetime(2024, 7, 8, 12, 30, 0, 250000, tzinfo=UTC)

    @pytest.mark.parametrize(
        "watermark_days_ago, expected_start_days_ago",
        [
            (None, LOGS_LOOKBACK_DAYS),
            (2, 2),
            # A watermark older than Mailgun's retention starts at the lookback edge instead.
            (LOGS_LOOKBACK_DAYS + 30, LOGS_LOOKBACK_DAYS),
        ],
    )
    def test_window_starts_at_the_watermark_or_the_lookback(self, watermark_days_ago, expected_start_days_ago):
        now = datetime.now(UTC)
        watermark = None if watermark_days_ago is None else now - timedelta(days=watermark_days_ago)

        result = _driver().run(
            "logs",
            lambda _request: ScriptedResponse(json={"items": [], "pagination": {}}),
            incremental_field="timestamp" if watermark else None,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        start = parsedate_to_datetime(result.requests[0].json()["start"])
        assert abs(start - (now - timedelta(days=expected_start_days_ago))) < timedelta(minutes=1)

    @pytest.mark.parametrize(
        "fraction, expected_start_delay",
        [
            ("", timedelta(0)),
            # The request carries whole seconds, so it can only start inside retention one second later.
            (".25", timedelta(seconds=1)),
        ],
    )
    def test_narrows_the_window_to_the_accounts_log_retention(self, fraction, expected_start_delay):
        retention_start = (datetime.now(UTC) - timedelta(days=4)).replace(microsecond=0)
        retention_time = retention_start + timedelta(seconds=float(fraction or 0))
        retention_message = (
            "start time 2024-07-01 00:00:00 +0000 UTC with log retention days 5 is before log retention time "
            f"{retention_start.strftime('%Y-%m-%d %H:%M:%S')}{fraction} +0000 UTC"
        )

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if parsedate_to_datetime(request.json()["start"]) < retention_time:
                return ScriptedResponse(status=400, json={"message": retention_message})
            return ScriptedResponse(json={"items": [_log_item("e1")], "pagination": {}})

        result = _driver().run("logs", respond)

        assert result.raised is None
        starts = [parsedate_to_datetime(request.json()["start"]) for request in result.requests]
        assert len(starts) == 2
        assert starts[1] == retention_start + expected_start_delay
        assert [row["id"] for row in result.rows] == ["e1"]

    @pytest.mark.parametrize(
        "message",
        [
            "invalid filter",
            # A retention time that doesn't move the window forward would only be rejected again.
            "start time is before log retention time 2000-01-01 00:00:00 +0000 UTC",
        ],
    )
    def test_other_bad_requests_still_fail_the_sync(self, message):
        result = _driver().run("logs", lambda _request: ScriptedResponse(status=400, json={"message": message}))

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1

    @pytest.mark.parametrize(
        "resume_token, saved_start, expected_tokens",
        [
            ("t5", "2024-07-01T00:00:00+00:00", ["t5"]),
            # An exhausted window has nothing left to read.
            (None, "2024-07-08T00:00:00+00:00", []),
        ],
    )
    def test_resume_reuses_the_saved_window_and_token(self, resume_token, saved_start, expected_tokens):
        resume_state = MailgunResumeConfig(
            logs_start=saved_start, logs_end="2024-07-08T00:00:00+00:00", logs_token=resume_token
        )

        result = _driver().run(
            "logs",
            lambda _request: ScriptedResponse(json={"items": [], "pagination": {}}),
            resume_state=resume_state,
        )

        assert result.raised is None
        bodies = [request.json() for request in result.requests]
        assert [body["pagination"].get("token") for body in bodies] == expected_tokens
        for body in bodies:
            assert parsedate_to_datetime(body["start"]) == datetime(2024, 7, 1, tzinfo=UTC)
            assert parsedate_to_datetime(body["end"]) == datetime(2024, 7, 8, tzinfo=UTC)


class TestFanOutEndpoints:
    def test_mailing_list_members_fan_out_over_every_list(self):
        lists_next = f"{US_BASE}/v3/lists/pages?page=next&address=b%40lists.example.com&limit=100"

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v3/lists/pages":
                if request.param("page") == "next":
                    return ScriptedResponse(json=_paging_page([], None))
                lists = [{"address": "a@lists.example.com"}, {"address": "b@lists.example.com"}]
                return ScriptedResponse(json=_paging_page(lists, lists_next))
            if request.path == "/v3/lists/a%40lists.example.com/members/pages" and request.param("page") is None:
                members = [{"address": "x@example.com", "subscribed": True}]
                return ScriptedResponse(json=_paging_page(members, f"{request.url}&page=next&address=x%40example.com"))
            return ScriptedResponse(json=_paging_page([], None))

        result = _driver().run("mailing_list_members", respond)

        assert result.raised is None
        assert [(row["list_address"], row["address"]) for row in result.rows] == [
            ("a@lists.example.com", "x@example.com")
        ]
        assert "/v3/lists/b%40lists.example.com/members/pages" in result.paths

    def test_subaccounts_read_their_own_response_key_across_skip_pages(self):
        page_size = MAILGUN_ENDPOINTS["subaccounts"].page_size

        def respond(request: RecordedRequest) -> ScriptedResponse:
            count = page_size if request.param("skip") == "0" else 1
            skip = int(request.param("skip") or 0)
            return ScriptedResponse(
                json={"subaccounts": [{"id": f"sub-{skip + i}"} for i in range(count)], "total": page_size + 1}
            )

        result = _driver().run("subaccounts", respond)

        assert result.raised is None
        assert result.params("skip") == ["0", str(page_size)]
        assert len(result.rows) == page_size + 1


class TestMailgunSourceResponse:
    def test_webhook_endpoint_yields_nothing_until_the_webhook_is_live(self):
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=False)

        response = mailgun_source(
            "key", "us", WEBHOOK_EVENTS_ENDPOINT, mock.MagicMock(), _make_manager(), webhook_manager
        )

        assert list(cast(Iterable[Any], response.items())) == []
        webhook_manager.get_items.assert_not_called()

    def test_webhook_endpoint_reads_pushed_rows_once_enabled(self):
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)

        response = mailgun_source(
            "key", "us", WEBHOOK_EVENTS_ENDPOINT, mock.MagicMock(), _make_manager(), webhook_manager
        )
        response.items()

        webhook_manager.get_items.assert_called_once_with(table_transformer=_webhook_table_transformer)


class TestWebhookTableTransformer:
    def test_keeps_the_latest_row_per_event_id_within_one_batch(self):
        table = table_from_py_list(
            [
                {"event-data": {"id": "evt_1", "event": "delivered", "timestamp": 1700000000.0}},
                {"event-data": {"id": "evt_1", "event": "delivered", "timestamp": 1700000900.0}},
                {"event-data": {"id": "evt_2", "event": "opened", "timestamp": 1700000100.0}},
            ]
        )

        rows = {row["id"]: row for row in _webhook_table_transformer(table).to_pylist()}

        assert set(rows) == {"evt_1", "evt_2"}
        assert rows["evt_1"]["timestamp"] == datetime.fromtimestamp(1700000900.0, tz=UTC)

    @pytest.mark.parametrize(
        "payloads",
        [
            [{"event-data": {"event": "delivered", "timestamp": 1700000000.0}}],
            [{"event-data": None}],
        ],
    )
    def test_drops_rows_that_cannot_be_merged(self, payloads):
        assert _webhook_table_transformer(table_from_py_list(payloads)).num_rows == 0

    def test_returns_no_rows_when_the_envelope_key_is_absent(self):
        table = table_from_py_list([{"something": "else"}])

        assert _webhook_table_transformer(table).num_rows == 0


def _webhook_list_response(webhooks: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json={"webhooks": webhooks})


class TestWebhookManagement:
    @staticmethod
    def _script(list_payloads: list[ScriptedResponse]) -> list[ScriptedResponse]:
        return [
            ScriptedResponse(json={"items": [{"name": "mg.example.com"}, {"name": "mg.other.com"}]}),
            *list_payloads,
        ]

    def test_create_is_idempotent_for_types_already_pointing_at_us(self):
        already = {webhook_type: {"urls": [POSTHOG_URL]} for webhook_type in WEBHOOK_TYPES}
        with scripted_network(
            self._script([_webhook_list_response(already), _webhook_list_response(already)])
        ) as network:
            result = create_webhook("key", "us", POSTHOG_URL)

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET", "GET", "GET"]

    def test_create_preserves_a_third_partys_url_on_the_same_event_type(self):
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v4/domains":
                return ScriptedResponse(json={"items": [{"name": "mg.example.com"}, {"name": "mg.other.com"}]})
            if request.method == "GET":
                return _webhook_list_response(
                    {"delivered": {"urls": ["https://other.example/hook"]}} if "mg.example.com" in request.path else {}
                )
            return ScriptedResponse(json={})

        with scripted_network(answer) as network:
            result = create_webhook("key", "us", POSTHOG_URL)

        assert result.success is True
        puts = [request for request in network.requests_log if request.method == "PUT"]
        assert len(puts) == 1
        assert puts[0].path.endswith("/v3/domains/mg.example.com/webhooks/delivered")
        assert parse_qs((puts[0].body or b"").decode())["url"] == [
            "https://other.example/hook",
            POSTHOG_URL,
        ]

    def test_create_leaves_a_full_event_type_alone_and_carries_on(self):
        # Mailgun caps a webhook type at three URLs, so this one can't take PostHog as well.
        full = {"delivered": {"urls": ["https://a/1", "https://b/2", "https://c/3"]}}

        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v4/domains":
                return ScriptedResponse(json={"items": [{"name": "mg.example.com"}, {"name": "mg.other.com"}]})
            if request.method == "GET":
                return _webhook_list_response(full if "mg.example.com" in request.path else {})
            return ScriptedResponse(json={})

        with scripted_network(answer) as network:
            result = create_webhook("key", "us", POSTHOG_URL)

        assert result.success is True
        assert all(request.method != "PUT" for request in network.requests_log)
        posted = [
            (request.url.split("?", 1)[0], parse_qs((request.body or b"").decode())["id"][0])
            for request in network.requests_log
            if request.method == "POST"
        ]
        assert ("https://api.mailgun.net/v3/domains/mg.example.com/webhooks", "delivered") not in posted
        assert ("https://api.mailgun.net/v3/domains/mg.other.com/webhooks", "delivered") in posted
        assert len(posted) == len(WEBHOOK_TYPES) * 2 - 1

    def test_create_fails_when_the_account_has_no_sending_domains(self):
        with scripted_network([ScriptedResponse(json={"items": []})]):
            result = create_webhook("key", "us", POSTHOG_URL)

        assert result.success is False
        assert "no sending domains" in (result.error or "")

    def test_create_fails_when_every_registration_is_refused(self):
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v4/domains":
                return ScriptedResponse(json={"items": [{"name": "mg.example.com"}, {"name": "mg.other.com"}]})
            if request.method == "GET":
                return _webhook_list_response({})
            return ScriptedResponse(status=403, json={})

        with scripted_network(answer):
            result = create_webhook("key", "us", POSTHOG_URL)

        assert result.success is False
        assert "manually" in (result.error or "")

    def test_delete_removes_only_our_url_and_keeps_other_consumers(self):
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v4/domains":
                return ScriptedResponse(json={"items": [{"name": "mg.example.com"}, {"name": "mg.other.com"}]})
            if request.method == "GET":
                return _webhook_list_response(
                    {
                        "delivered": {"urls": [POSTHOG_URL, "https://other.example/hook"]},
                        "opened": {"urls": [POSTHOG_URL]},
                        "clicked": {"urls": ["https://other.example/hook"]},
                    }
                    if "mg.example.com" in request.path
                    else {}
                )
            return ScriptedResponse(json={})

        with scripted_network(answer) as network:
            result = delete_webhook("key", "us", POSTHOG_URL)

        assert result.success is True
        puts = [request for request in network.requests_log if request.method == "PUT"]
        deletes = [request for request in network.requests_log if request.method == "DELETE"]
        assert parse_qs((puts[0].body or b"").decode())["url"] == ["https://other.example/hook"]
        assert len(deletes) == 1
        assert deletes[0].path.endswith("/webhooks/opened")

    def test_delete_surfaces_a_failure_rather_than_reporting_success(self):
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v4/domains":
                return ScriptedResponse(json={"items": [{"name": "mg.example.com"}, {"name": "mg.other.com"}]})
            if request.method == "GET":
                return _webhook_list_response(
                    {"opened": {"urls": [POSTHOG_URL]}} if "mg.example.com" in request.path else {}
                )
            return ScriptedResponse(status=403, json={})

        with scripted_network(answer):
            result = delete_webhook("key", "us", POSTHOG_URL)

        assert result.success is False
        assert "403" in (result.error or "")

    def test_info_reports_the_registered_event_types(self):
        script = self._script(
            [
                _webhook_list_response(
                    {"delivered": {"urls": [POSTHOG_URL]}, "opened": {"url": "https://other.example/hook"}}
                ),
                _webhook_list_response({"clicked": {"urls": [POSTHOG_URL]}}),
            ]
        )
        with scripted_network(script):
            info = get_external_webhook_info("key", "us", POSTHOG_URL)

        assert info.exists is True
        # Must speak Mailgun's webhook type ids so the UI can diff them against
        # `get_desired_webhook_events`.
        assert info.enabled_events == ["clicked", "delivered"]

    def test_info_reports_absent_when_no_domain_points_at_us(self):
        script = self._script(
            [
                _webhook_list_response({"delivered": {"urls": ["https://other.example/hook"]}}),
                _webhook_list_response({}),
            ]
        )
        with scripted_network(script):
            info = get_external_webhook_info("key", "us", POSTHOG_URL)

        assert info.exists is False

    def test_info_reports_the_error_instead_of_raising(self):
        with scripted_network([ScriptedResponse(status=401, json={})]):
            info = get_external_webhook_info("key", "us", POSTHOG_URL)

        assert info.exists is False
        assert "401" in (info.error or "")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.create_webhook")
    def test_sync_re_registers_so_new_domains_get_covered(self, mock_create):
        mock_create.return_value = WebhookCreationResult(success=True)

        result = sync_webhook_events("key", "us", POSTHOG_URL)

        assert result.success is True
        mock_create.assert_called_once_with("key", "us", POSTHOG_URL)
