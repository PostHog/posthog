import time
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookCreationResult
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun import (
    FORBIDDEN_ERROR,
    INVALID_KEY_ERROR,
    UNREACHABLE_ERROR,
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
    get_rows,
    mailgun_source,
    sync_webhook_events,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.settings import (
    ENDPOINTS,
    MAILGUN_ENDPOINTS,
    WEBHOOK_EVENTS_ENDPOINT,
    WEBHOOK_TYPES,
)

US_BASE = "https://api.mailgun.net"
POSTHOG_URL = "https://us.posthog.com/public/webhooks/abc"


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


class TestInitialUrl:
    def test_domain_is_url_quoted_in_path(self):
        url = _initial_url(US_BASE, MAILGUN_ENDPOINTS["bounces"], "ex/ample.com")
        assert url is not None
        assert "/v3/ex%2Fample.com/bounces" in url

    def test_domain_scoped_endpoint_without_domain_raises(self):
        with pytest.raises(ValueError):
            _initial_url(US_BASE, MAILGUN_ENDPOINTS["events"], None)


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
            (200, (True, None)),
            (401, (False, INVALID_KEY_ERROR)),
            (404, (False, INVALID_KEY_ERROR)),
            (403, (False, FORBIDDEN_ERROR)),
            (500, (False, UNREACHABLE_ERROR)),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = _response({}, status_code)

        assert validate_credentials("key", "us") == expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "us") == (False, UNREACHABLE_ERROR)


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


class TestGetRows:
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

    @pytest.mark.parametrize(
        "self_referencing, expected_requests, expected_rows",
        [(True, 2, 2), (False, 3, 4)],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_repeating_paging_cursor_terminates(self, mock_session, self_referencing, expected_requests, expected_rows):
        # Mailgun's tags endpoint re-serves its terminal page behind a stable `page=next&tag=<last>`
        # cursor instead of returning an empty page. Unguarded, the chain re-yields the same rows
        # until the activity is killed, and every repeat is billed as a synced row. Two shapes: the
        # cursor pointing at the page it came from, and a two-URL cycle between pages.
        items = [{"tag": "t1"}, {"tag": "t2"}]
        page_a = f"{US_BASE}/v3/a.com/tags?limit=1000"
        page_b = f"{page_a}&page=next&tag=t2"
        next_of_a = page_a if self_referencing else page_b

        requests_made: list[str] = []

        def fake_get(url, **kwargs):
            requests_made.append(url)
            if len(requests_made) > 6:
                raise AssertionError("pagination did not terminate")
            if "/v4/domains" in url:
                return _response({"items": [{"name": "a.com"}]})
            return _response(_paging_page(items, next_of_a if url == page_a else page_a))

        mock_session.return_value.get.side_effect = fake_get

        batches = list(get_rows("key", "us", "tags", mock.MagicMock(), _make_manager()))

        assert len(requests_made) == expected_requests
        assert sum(len(batch) for batch in batches) == expected_rows

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.MAX_PAGES_PER_CHAIN", 3
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_paging_stops_at_the_page_cap(self, mock_session):
        # A cursor that mints a fresh URL for every page never repeats, so the seen-URL guard can't
        # see it and only the page cap ends the chain.
        pages_fetched = 0

        def fake_get(url, **kwargs):
            nonlocal pages_fetched
            if "/v4/domains" in url:
                return _response({"items": [{"name": "a.com"}]})
            pages_fetched += 1
            if pages_fetched > 10:
                raise AssertionError("pagination did not terminate")
            return _response(
                _paging_page([{"tag": f"t{pages_fetched}"}], f"{US_BASE}/v3/a.com/tags?page=next&tag=t{pages_fetched}")
            )

        mock_session.return_value.get.side_effect = fake_get
        logger = mock.MagicMock()

        batches = list(get_rows("key", "us", "tags", logger, _make_manager()))

        assert pages_fetched == 3
        assert sum(len(batch) for batch in batches) == 3
        assert "exceeded 3 pages" in logger.warning.call_args.args[0]

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
    def test_resume_with_completed_state_yields_nothing(self, mock_session):
        manager = _make_manager(MailgunResumeConfig(next_url=None, current_domain=None, pending_domains=[]))

        batches = list(get_rows("key", "us", "events", mock.MagicMock(), manager))

        assert batches == []
        mock_session.return_value.get.assert_not_called()

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
    def test_domain_scoped_endpoints_have_domain_in_primary_key(self, endpoint):
        config = MAILGUN_ENDPOINTS[endpoint]
        if config.domain_scoped:
            assert "domain" in config.primary_keys

    @pytest.mark.parametrize("config", list(MAILGUN_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"timestamp", "created_at"}

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


def _webhook_list_response(webhooks: dict[str, Any]) -> mock.MagicMock:
    return _response({"webhooks": webhooks})


class TestWebhookManagement:
    def _session(self, mock_session, list_payloads: list[mock.MagicMock]) -> mock.MagicMock:
        """Wire a session whose GETs answer the domain listing first, then one webhook listing
        per domain."""
        session = mock_session.return_value
        session.get.side_effect = [
            _response({"items": [{"name": "mg.example.com"}, {"name": "mg.other.com"}]}),
            *list_payloads,
        ]
        return session

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_create_is_idempotent_for_types_already_pointing_at_us(self, mock_session):
        already = {webhook_type: {"urls": [POSTHOG_URL]} for webhook_type in WEBHOOK_TYPES}
        session = self._session(mock_session, [_webhook_list_response(already), _webhook_list_response(already)])

        result = create_webhook("key", "us", POSTHOG_URL)

        assert result.success is True
        session.post.assert_not_called()
        session.put.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_create_preserves_a_third_partys_url_on_the_same_event_type(self, mock_session):
        session = self._session(
            mock_session,
            [
                _webhook_list_response({"delivered": {"urls": ["https://other.example/hook"]}}),
                _webhook_list_response({}),
            ],
        )
        session.post.return_value = _response({})
        session.put.return_value = _response({})

        create_webhook("key", "us", POSTHOG_URL)

        session.put.assert_called_once()
        assert session.put.call_args.args[0].endswith("/v3/domains/mg.example.com/webhooks/delivered")
        assert session.put.call_args.kwargs["data"] == [
            ("url", "https://other.example/hook"),
            ("url", POSTHOG_URL),
        ]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_create_leaves_a_full_event_type_alone_and_carries_on(self, mock_session):
        # Mailgun caps a webhook type at three URLs, so this one can't take PostHog as well.
        full = {"delivered": {"urls": ["https://a/1", "https://b/2", "https://c/3"]}}
        session = self._session(mock_session, [_webhook_list_response(full), _webhook_list_response({})])
        session.post.return_value = _response({})

        result = create_webhook("key", "us", POSTHOG_URL)

        # Every other type on that domain, and every type on the next one, still registers.
        assert result.success is True
        session.put.assert_not_called()
        posted = [(call.args[0], call.kwargs["data"]["id"]) for call in session.post.call_args_list]
        assert ("https://api.mailgun.net/v3/domains/mg.example.com/webhooks", "delivered") not in posted
        assert ("https://api.mailgun.net/v3/domains/mg.other.com/webhooks", "delivered") in posted
        assert len(posted) == len(WEBHOOK_TYPES) * 2 - 1

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_create_fails_when_the_account_has_no_sending_domains(self, mock_session):
        mock_session.return_value.get.return_value = _response({"items": []})

        result = create_webhook("key", "us", POSTHOG_URL)

        assert result.success is False
        assert "no sending domains" in (result.error or "")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_create_fails_when_every_registration_is_refused(self, mock_session):
        session = self._session(mock_session, [_webhook_list_response({}), _webhook_list_response({})])
        session.post.return_value = _error_response(403, f"{US_BASE}/v3/domains/mg.example.com/webhooks")

        result = create_webhook("key", "us", POSTHOG_URL)

        assert result.success is False
        assert "manually" in (result.error or "")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_delete_removes_only_our_url_and_keeps_other_consumers(self, mock_session):
        session = self._session(
            mock_session,
            [
                _webhook_list_response(
                    {
                        "delivered": {"urls": [POSTHOG_URL, "https://other.example/hook"]},
                        "opened": {"urls": [POSTHOG_URL]},
                        "clicked": {"urls": ["https://other.example/hook"]},
                    }
                ),
                _webhook_list_response({}),
            ],
        )
        session.put.return_value = _response({})
        session.delete.return_value = _response({})

        result = delete_webhook("key", "us", POSTHOG_URL)

        assert result.success is True
        assert session.put.call_args.kwargs["data"] == [("url", "https://other.example/hook")]
        assert session.delete.call_count == 1
        assert session.delete.call_args.args[0].endswith("/webhooks/opened")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_delete_surfaces_a_failure_rather_than_reporting_success(self, mock_session):
        session = self._session(
            mock_session,
            [_webhook_list_response({"opened": {"urls": [POSTHOG_URL]}}), _webhook_list_response({})],
        )
        session.delete.return_value = _error_response(403, f"{US_BASE}/v3/domains/mg.example.com/webhooks/opened")

        result = delete_webhook("key", "us", POSTHOG_URL)

        assert result.success is False
        assert "403" in (result.error or "")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_info_reports_the_registered_event_types(self, mock_session):
        self._session(
            mock_session,
            [
                _webhook_list_response(
                    {"delivered": {"urls": [POSTHOG_URL]}, "opened": {"url": "https://other.example/hook"}}
                ),
                _webhook_list_response({"clicked": {"urls": [POSTHOG_URL]}}),
            ],
        )

        info = get_external_webhook_info("key", "us", POSTHOG_URL)

        assert info.exists is True
        # Must speak Mailgun's webhook type ids so the UI can diff them against
        # `get_desired_webhook_events`.
        assert info.enabled_events == ["clicked", "delivered"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_info_reports_absent_when_no_domain_points_at_us(self, mock_session):
        self._session(
            mock_session,
            [
                _webhook_list_response({"delivered": {"urls": ["https://other.example/hook"]}}),
                _webhook_list_response({}),
            ],
        )

        info = get_external_webhook_info("key", "us", POSTHOG_URL)

        assert info.exists is False

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_info_reports_the_error_instead_of_raising(self, mock_session):
        mock_session.return_value.get.return_value = _error_response(401, f"{US_BASE}/v4/domains")

        info = get_external_webhook_info("key", "us", POSTHOG_URL)

        assert info.exists is False
        assert "401" in (info.error or "")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.create_webhook")
    def test_sync_re_registers_so_new_domains_get_covered(self, mock_create):
        mock_create.return_value = WebhookCreationResult(success=True)

        result = sync_webhook_events("key", "us", POSTHOG_URL)

        assert result.success is True
        mock_create.assert_called_once_with("key", "us", POSTHOG_URL)
