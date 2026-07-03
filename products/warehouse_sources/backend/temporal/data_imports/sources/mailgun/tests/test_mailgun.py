import time
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun import (
    MAX_RETRY_AFTER_SECONDS,
    MailgunResumeConfig,
    MailgunRetryableError,
    _epoch_to_datetime,
    _increment_skip,
    _initial_url,
    _next_page_url,
    _normalize_row,
    _parse_retry_after,
    _retry_wait,
    _to_epoch,
    base_url_for_region,
    get_domain_names,
    get_rows,
    mailgun_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.settings import (
    ENDPOINTS,
    MAILGUN_ENDPOINTS,
)

US_BASE = "https://api.mailgun.net"


def _make_manager(resume_state: MailgunResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(payload: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.json.return_value = payload
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = {}
    return response


def _error_response(status_code: int, url: str) -> mock.MagicMock:
    response = _response({}, status_code)
    response.text = "Bad Request"
    response.raise_for_status.side_effect = requests.HTTPError(
        f"{status_code} Client Error: Bad Request for url: {url}", response=response
    )
    return response


def _paging_page(items: list[dict[str, Any]], next_url: str | None) -> dict[str, Any]:
    paging: dict[str, Any] = {"first": "f", "last": "l"}
    if next_url is not None:
        paging["next"] = next_url
    return {"items": items, "paging": paging}


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


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

    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://api.mailgun.net"),
            ("eu", "https://api.eu.mailgun.net"),
            ("EU", "https://api.eu.mailgun.net"),
            ("unknown", "https://api.mailgun.net"),
        ],
    )
    def test_base_url_for_region(self, region, expected):
        assert base_url_for_region(region) == expected

    def test_retry_wait_honors_retry_after(self):
        retry_state = mock.MagicMock()
        retry_state.outcome.exception.return_value = MailgunRetryableError("rate limited", retry_after=42)
        assert _retry_wait(retry_state) == 42

    def test_retry_wait_caps_retry_after(self):
        retry_state = mock.MagicMock()
        retry_state.outcome.exception.return_value = MailgunRetryableError("rate limited", retry_after=9999)
        assert _retry_wait(retry_state) == MAX_RETRY_AFTER_SECONDS

    def test_retry_wait_falls_back_to_exponential(self):
        retry_state = mock.MagicMock()
        retry_state.outcome.exception.return_value = MailgunRetryableError("server error")
        retry_state.attempt_number = 1
        wait = _retry_wait(retry_state)
        assert 0 <= wait <= 61


class TestInitialUrl:
    def test_events_url_includes_ascending_begin_and_end(self):
        url = _initial_url(US_BASE, MAILGUN_ENDPOINTS["events"], "example.com", begin=1700000000)

        assert url is not None
        assert url.startswith(f"{US_BASE}/v3/example.com/events?")
        query = _query(url)
        assert query["limit"] == ["300"]
        assert query["ascending"] == ["yes"]
        assert query["begin"] == ["1700000000"]
        assert int(query["end"][0]) <= int(time.time()) - 30 * 60

    def test_events_url_without_begin_on_full_refresh(self):
        url = _initial_url(US_BASE, MAILGUN_ENDPOINTS["events"], "example.com", begin=None)

        assert url is not None
        query = _query(url)
        assert "begin" not in query
        assert query["ascending"] == ["yes"]

    def test_events_url_is_none_when_watermark_inside_lag_window(self):
        assert _initial_url(US_BASE, MAILGUN_ENDPOINTS["events"], "example.com", begin=int(time.time())) is None

    def test_domain_is_url_quoted_in_path(self):
        url = _initial_url(US_BASE, MAILGUN_ENDPOINTS["bounces"], "ex/ample.com")
        assert url is not None
        assert "/v3/ex%2Fample.com/bounces" in url

    def test_skip_endpoint_starts_at_zero(self):
        url = _initial_url(US_BASE, MAILGUN_ENDPOINTS["domains"], None)
        assert url is not None
        query = _query(url)
        assert query["skip"] == ["0"]
        assert query["limit"] == ["1000"]

    def test_domain_scoped_endpoint_without_domain_raises(self):
        with pytest.raises(ValueError):
            _initial_url(US_BASE, MAILGUN_ENDPOINTS["events"], None)

    @pytest.mark.parametrize("endpoint", ["bounces", "complaints", "unsubscribes", "tags", "templates"])
    def test_full_refresh_endpoints_have_no_time_filters(self, endpoint):
        url = _initial_url(US_BASE, MAILGUN_ENDPOINTS[endpoint], "example.com", begin=1700000000)
        assert url is not None
        query = _query(url)
        assert "begin" not in query
        assert "ascending" not in query


class TestPagination:
    def test_increment_skip(self):
        url = _increment_skip(f"{US_BASE}/v4/domains?limit=1000&skip=0", 1000)
        assert _query(url)["skip"] == ["1000"]

    def test_increment_skip_without_existing_skip_param(self):
        url = _increment_skip(f"{US_BASE}/v4/domains?limit=1000", 1000)
        assert _query(url)["skip"] == ["1000"]

    def test_skip_pagination_stops_on_partial_page(self):
        config = MAILGUN_ENDPOINTS["domains"]
        assert _next_page_url(config, f"{US_BASE}/v4/domains?limit=1000&skip=0", {}, config.page_size - 1) is None

    def test_skip_pagination_continues_on_full_page(self):
        config = MAILGUN_ENDPOINTS["domains"]
        next_url = _next_page_url(config, f"{US_BASE}/v4/domains?limit=1000&skip=0", {}, config.page_size)
        assert next_url is not None
        assert _query(next_url)["skip"] == ["1000"]

    def test_paging_stops_on_empty_items(self):
        config = MAILGUN_ENDPOINTS["events"]
        data = _paging_page([], "https://api.mailgun.net/v3/example.com/events/next-token")
        assert _next_page_url(config, "current", data, 0) is None

    def test_paging_follows_next_url_when_items_present(self):
        config = MAILGUN_ENDPOINTS["events"]
        data = _paging_page([{"id": "a"}], "https://api.mailgun.net/v3/example.com/events/next-token")
        assert _next_page_url(config, "current", data, 1) == "https://api.mailgun.net/v3/example.com/events/next-token"

    def test_paging_stops_when_next_missing(self):
        config = MAILGUN_ENDPOINTS["events"]
        data = _paging_page([{"id": "a"}], None)
        assert _next_page_url(config, "current", data, 1) is None


class TestNormalizeRow:
    def test_injects_domain_for_domain_scoped_endpoints(self):
        row = _normalize_row(MAILGUN_ENDPOINTS["bounces"], "example.com", {"address": "a@b.com"})
        assert row == {"address": "a@b.com", "domain": "example.com"}

    def test_converts_event_timestamp_to_datetime(self):
        row = _normalize_row(MAILGUN_ENDPOINTS["events"], "example.com", {"id": "x", "timestamp": 1521472262.9})
        assert row["timestamp"] == datetime.fromtimestamp(1521472262.9, tz=UTC)
        assert row["domain"] == "example.com"

    def test_leaves_account_level_rows_untouched(self):
        row = _normalize_row(MAILGUN_ENDPOINTS["mailing_lists"], None, {"address": "list@example.com"})
        assert row == {"address": "list@example.com"}

    def test_does_not_mutate_original_item(self):
        item = {"id": "x", "timestamp": 1521472262.9}
        _normalize_row(MAILGUN_ENDPOINTS["events"], "example.com", item)
        assert item == {"id": "x", "timestamp": 1521472262.9}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = _response({}, status_code)

        assert validate_credentials("key", "us") is expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "us") is False

    @pytest.mark.parametrize(
        "region, expected_host",
        [
            ("us", "https://api.mailgun.net/v4/domains"),
            ("eu", "https://api.eu.mailgun.net/v4/domains"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_validate_credentials_targets_region_host(self, mock_session, region, expected_host):
        mock_session.return_value.get.return_value = _response({}, 200)

        validate_credentials("key", region)

        assert mock_session.return_value.get.call_args.args[0] == expected_host

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_validate_credentials_uses_basic_auth(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, 200)

        validate_credentials("key-123", "us")

        assert mock_session.return_value.get.call_args.kwargs["auth"] == ("api", "key-123")


class TestGetDomainNames:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_collects_names_across_skip_pages(self, mock_session):
        page_size = MAILGUN_ENDPOINTS["domains"].page_size
        full_page = {"items": [{"name": f"domain-{i}.com"} for i in range(page_size)]}
        partial_page = {"items": [{"name": "last.com"}]}
        mock_session.return_value.get.side_effect = [_response(full_page), _response(partial_page)]

        names = get_domain_names("key", US_BASE, mock.MagicMock())

        assert len(names) == page_size + 1
        assert names[-1] == "last.com"
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert _query(second_url)["skip"] == [str(page_size)]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_skips_items_without_a_name(self, mock_session):
        mock_session.return_value.get.return_value = _response({"items": [{"name": "a.com"}, {"id": "no-name"}]})

        assert get_domain_names("key", US_BASE, mock.MagicMock()) == ["a.com"]


class TestGetRows:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_account_level_endpoint_paginates_via_paging_next(self, mock_session):
        next_url = f"{US_BASE}/v3/lists/pages?limit=100&page=next&address=b%40x.com"
        mock_session.return_value.get.side_effect = [
            _response(_paging_page([{"address": "a@x.com"}, {"address": "b@x.com"}], next_url)),
            _response(_paging_page([], next_url)),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", "us", "mailing_lists", mock.MagicMock(), manager))

        assert [row["address"] for batch in batches for row in batch] == ["a@x.com", "b@x.com"]
        # State saved after the yielded batch and again when the chain terminates.
        saved_states = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved_states[0].next_url == next_url
        assert saved_states[-1].next_url is None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_domains_endpoint_uses_skip_pagination(self, mock_session):
        page_size = MAILGUN_ENDPOINTS["domains"].page_size
        full_page = {"items": [{"id": f"id-{i}", "name": f"d{i}.com"} for i in range(page_size)]}
        partial_page = {"items": [{"id": "id-last", "name": "last.com"}]}
        mock_session.return_value.get.side_effect = [_response(full_page), _response(partial_page)]

        manager = _make_manager()
        batches = list(get_rows("key", "us", "domains", mock.MagicMock(), manager))

        assert sum(len(batch) for batch in batches) == page_size + 1
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert _query(second_url)["skip"] == [str(page_size)]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_domain_scoped_endpoint_fans_out_over_domains(self, mock_session):
        domains_page = {"items": [{"name": "a.com"}, {"name": "b.com"}]}
        a_events = _paging_page([{"id": "e1", "timestamp": 1700000000.5}], f"{US_BASE}/v3/a.com/events/next")
        a_empty = _paging_page([], None)
        b_events = _paging_page([{"id": "e2", "timestamp": 1700000100.5}], f"{US_BASE}/v3/b.com/events/next")
        b_empty = _paging_page([], None)
        mock_session.return_value.get.side_effect = [
            _response(domains_page),
            _response(a_events),
            _response(a_empty),
            _response(b_events),
            _response(b_empty),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", "us", "events", mock.MagicMock(), manager))

        rows = [row for batch in batches for row in batch]
        assert [(row["id"], row["domain"]) for row in rows] == [("e1", "a.com"), ("e2", "b.com")]
        assert rows[0]["timestamp"] == datetime.fromtimestamp(1700000000.5, tz=UTC)

        first_events_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert first_events_url.startswith(f"{US_BASE}/v3/a.com/events?")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_incremental_run_passes_begin_from_watermark(self, mock_session):
        domains_page = {"items": [{"name": "a.com"}]}
        empty = _paging_page([], None)
        mock_session.return_value.get.side_effect = [_response(domains_page), _response(empty)]

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "us",
                "events",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC),
                incremental_field="timestamp",
            )
        )

        events_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert _query(events_url)["begin"] == ["1700000000"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_incremental_watermark_inside_lag_window_skips_fetch(self, mock_session):
        domains_page = {"items": [{"name": "a.com"}, {"name": "b.com"}]}
        mock_session.return_value.get.side_effect = [_response(domains_page)]

        manager = _make_manager()
        batches = list(
            get_rows(
                "key",
                "us",
                "events",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=int(time.time()),
                incremental_field="timestamp",
            )
        )

        assert batches == []
        # Only the domain listing was fetched; both domains were skipped.
        assert mock_session.return_value.get.call_count == 1

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_resumes_mid_chain_without_relisting_domains(self, mock_session):
        resume_url = f"{US_BASE}/v3/a.com/events/page-token"
        resume = MailgunResumeConfig(next_url=resume_url, current_domain="a.com", pending_domains=["b.com"])
        a_empty = _paging_page([{"id": "e9", "timestamp": 1700000000.0}], None)
        b_page = _paging_page([], None)
        mock_session.return_value.get.side_effect = [_response(a_empty), _response(b_page)]

        manager = _make_manager(resume)
        batches = list(get_rows("key", "us", "events", mock.MagicMock(), manager))

        # First request goes straight to the saved page URL — no /v4/domains listing.
        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url
        rows = [row for batch in batches for row in batch]
        assert [(row["id"], row["domain"]) for row in rows] == [("e9", "a.com")]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_resume_with_completed_state_yields_nothing(self, mock_session):
        manager = _make_manager(MailgunResumeConfig(next_url=None, current_domain=None, pending_domains=[]))

        batches = list(get_rows("key", "us", "events", mock.MagicMock(), manager))

        assert batches == []
        mock_session.return_value.get.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_state_saved_after_each_yielded_batch(self, mock_session):
        domains_page = {"items": [{"name": "a.com"}]}
        next_url = f"{US_BASE}/v3/a.com/bounces?page=next&address=x"
        page_one = _paging_page([{"address": "x@y.com", "created_at": "Fri, 21 Oct 2011 11:02:55 GMT"}], next_url)
        page_two = _paging_page([], None)
        mock_session.return_value.get.side_effect = [_response(domains_page), _response(page_one), _response(page_two)]

        manager = _make_manager()
        list(get_rows("key", "us", "bounces", mock.MagicMock(), manager))

        saved_states = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved_states[0].next_url == next_url
        assert saved_states[0].current_domain == "a.com"
        assert saved_states[-1].next_url is None
        assert saved_states[-1].pending_domains == []

    @pytest.mark.parametrize("status_code", [400, 401, 403])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_domain_scoped_access_error_skips_domain_and_continues_fan_out(self, mock_session, status_code):
        # The account lists a domain that can't be queried (disabled / unverified for 400, or a
        # domain the key has no access to for 401/403). It must skip that domain, not abort the
        # whole fan-out, so b.com still imports. A global credential failure 401s the /v4/domains
        # listing instead, which never reaches the fan-out and stays non-retryable.
        domains_page = {"items": [{"name": "a.com"}, {"name": "b.com"}]}
        a_bad = _error_response(status_code, f"{US_BASE}/v3/a.com/events")
        b_events = _paging_page([{"id": "e2", "timestamp": 1700000100.5}], None)
        mock_session.return_value.get.side_effect = [
            _response(domains_page),
            a_bad,
            _response(b_events),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", "us", "events", mock.MagicMock(), manager))

        rows = [row for batch in batches for row in batch]
        assert [(row["id"], row["domain"]) for row in rows] == [("e2", "b.com")]
        # The skipped domain leaves no in-flight chain behind, and the fan-out completes cleanly.
        saved_states = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved_states[0].current_domain is None
        assert saved_states[-1].next_url is None
        assert saved_states[-1].pending_domains == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_domain_listing_401_still_raises(self, mock_session):
        # A 401 on the /v4/domains listing is a global credential failure, not a single bad
        # domain — it must surface (and stay non-retryable) rather than be skipped per-domain.
        mock_session.return_value.get.return_value = _error_response(401, f"{US_BASE}/v4/domains")

        manager = _make_manager()
        with pytest.raises(requests.HTTPError, match="401 Client Error"):
            list(get_rows("key", "us", "events", mock.MagicMock(), manager))

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_account_level_400_still_raises(self, mock_session):
        # A 400 on a non-domain-scoped endpoint means our request is wrong, not a bad domain —
        # it must surface rather than be silently skipped.
        mock_session.return_value.get.return_value = _error_response(400, f"{US_BASE}/v3/lists/pages")

        manager = _make_manager()
        with pytest.raises(requests.HTTPError, match="400 Client Error"):
            list(get_rows("key", "us", "mailing_lists", mock.MagicMock(), manager))

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_domain_scoped_500_still_raises(self, mock_session):
        # Server errors are transient and retryable — they must not be swallowed as a skip.
        domains_page = {"items": [{"name": "a.com"}]}
        server_error = _response({}, 500)
        mock_session.return_value.get.side_effect = [_response(domains_page), *([server_error] * 10)]

        manager = _make_manager()
        with pytest.raises(MailgunRetryableError):
            with mock.patch("tenacity.nap.time.sleep", return_value=None):
                list(get_rows("key", "us", "events", mock.MagicMock(), manager))

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_non_ok_response_raises(self, mock_session):
        response = _response({}, 401)
        response.raise_for_status.side_effect = Exception("401 Client Error")
        response.text = "unauthorized"
        mock_session.return_value.get.return_value = response

        manager = _make_manager()
        with pytest.raises(Exception, match="401 Client Error"):
            list(get_rows("key", "us", "mailing_lists", mock.MagicMock(), manager))

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    def test_retries_on_429_then_succeeds(self, _mock_sleep, mock_session):
        rate_limited = _response({}, 429)
        rate_limited.headers = {"Retry-After": "1"}
        ok_page = _response(_paging_page([{"address": "a@x.com"}], None))
        empty_page = _response(_paging_page([], None))
        mock_session.return_value.get.side_effect = [rate_limited, ok_page, empty_page]

        manager = _make_manager()
        batches = list(get_rows("key", "us", "mailing_lists", mock.MagicMock(), manager))

        assert [row["address"] for batch in batches for row in batch] == ["a@x.com"]


class TestMailgunSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = MAILGUN_ENDPOINTS[endpoint]
        response = mailgun_source("key", "us", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
            assert response.partition_format == config.partition_format
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_domain_scoped_endpoints_have_domain_in_primary_key(self, endpoint):
        config = MAILGUN_ENDPOINTS[endpoint]
        if config.domain_scoped:
            assert "domain" in config.primary_keys

    @pytest.mark.parametrize("config", list(MAILGUN_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"timestamp", "created_at"}
