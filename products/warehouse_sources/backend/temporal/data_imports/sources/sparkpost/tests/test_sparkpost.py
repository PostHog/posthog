import json
import base64
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import pyarrow as pa
import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import (
    WEBHOOK_BATCH_KEY,
    WEBHOOK_EVENT_TYPES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.sparkpost import (
    DEFAULT_REGION,
    SparkPostLinksPaginator,
    SparkPostResumeConfig,
    _format_from,
    _webhook_table_transformer,
    base_url,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    sparkpost_source,
    sync_webhook_events,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the sparkpost module.
SPARKPOST_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.sparkpost.make_tracked_session"
)

HOST = "https://api.sparkpost.com"


def _response(results: Any, links: Any = None) -> Response:
    body: dict[str, Any] = {"results": results}
    if links is not None:
        body["links"] = links
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SparkPostResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session, capturing each request's URL and params AT SEND TIME.

    ``request.params``/``request.url`` are mutated in place across pages, so inspecting them after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    url_snapshots: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots, param_snapshots


def _rows(endpoint: str, manager: mock.MagicMock, **overrides: Any) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "region": "us",
        "api_key": "key",
        "endpoint": endpoint,
        "team_id": 1,
        "job_id": "j",
        "resumable_source_manager": manager,
    }
    kwargs.update(overrides)
    response = sparkpost_source(**kwargs)
    return [row for page in cast("Iterable[Any]", response.items()) for row in page]


class TestBaseUrl:
    @pytest.mark.parametrize(
        ("region", "expected"),
        [
            ("us", "https://api.sparkpost.com"),
            ("eu", "https://api.eu.sparkpost.com"),
            ("US", "https://api.sparkpost.com"),
            # Unknown / spoofed regions fall back to the default US host.
            ("evil", "https://api.sparkpost.com"),
            (None, "https://api.sparkpost.com"),
        ],
    )
    def test_base_url(self, region: Any, expected: str) -> None:
        assert base_url(region) == expected

    def test_default_region_is_us(self) -> None:
        assert DEFAULT_REGION == "us"


class TestFormatFrom:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58"),
            # Truncated to the minute; seconds dropped.
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30"),
            # Naive datetimes are treated as UTC.
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58"),
            (date(2026, 3, 4), "2026-03-04T00:00"),
            # ISO 8601 strings (how the stored watermark can come back) are parsed, not passed
            # through — SparkPost rejects a raw ``...T00:00:00Z`` value.
            ("2026-01-01T00:00:00Z", "2026-01-01T00:00"),
            ("2026-01-15T10:30:45.123456Z", "2026-01-15T10:30"),
            ("2026-03-04T02:58:14+00:00", "2026-03-04T02:58"),
            # A genuinely unparseable string still falls through unchanged.
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_from(self, value: Any, expected: str) -> None:
        assert _format_from(value) == expected

    def test_no_timezone_offset_in_output(self) -> None:
        assert "+00:00" not in _format_from(datetime(2026, 3, 4, tzinfo=UTC))


class TestLinksPaginator:
    """The cursor paginator that walks SparkPost's ``links: [{href, rel}]`` next link, resolving a
    relative href against the host and re-pinning it there (SSRF guard)."""

    def _next_url(self, links: Any, data: Any = None) -> str | None:
        rows = data if data is not None else [{"event_id": "1"}]
        paginator = SparkPostLinksPaginator(HOST)
        paginator.update_state(_response(rows, links=links), rows)
        return paginator._next_url if paginator.has_next_page else None

    def test_follows_relative_next_href(self) -> None:
        assert (
            self._next_url([{"href": "/api/v1/events/message?cursor=abc&per_page=1000", "rel": "next"}])
            == "https://api.sparkpost.com/api/v1/events/message?cursor=abc&per_page=1000"
        )

    def test_follows_absolute_next_href(self) -> None:
        assert (
            self._next_url([{"href": "https://api.sparkpost.com/api/v1/events/message?cursor=abc", "rel": "next"}])
            == "https://api.sparkpost.com/api/v1/events/message?cursor=abc"
        )

    def test_no_next_rel_terminates(self) -> None:
        assert self._next_url([{"href": "/api/v1/events/message?cursor=x", "rel": "previous"}]) is None

    def test_no_links_terminates(self) -> None:
        assert self._next_url(None) is None

    def test_empty_page_terminates_without_following_next(self) -> None:
        # A page that returned no rows stops even when a next link is present.
        assert self._next_url([{"href": "/api/v1/events/message?cursor=x", "rel": "next"}], data=[]) is None

    @pytest.mark.parametrize(
        "next_href",
        [
            "https://evil.example.com/steal",  # off-host
            "http://api.sparkpost.com/api/v1/events/message",  # non-https
            "https://api.sparkpost.com.evil.com/api/v1/events/message",  # look-alike host
        ],
    )
    def test_rejects_offhost_next(self, next_href: str) -> None:
        assert self._next_url([{"href": next_href, "rel": "next"}]) is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            # 403 = genuine key without the Account scope used by the probe; don't block connecting.
            (403, True),
            (500, False),
        ],
    )
    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected_valid: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        is_valid, error = validate_credentials("us", "key")

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_request_exception_is_caught(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        is_valid, error = validate_credentials("us", "key")
        assert is_valid is False
        assert error is not None


class TestSparkPostSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expected_pk", "expect_partition"),
        [
            ("events", ["event_id"], True),
            ("suppression_list", ["recipient", "type"], True),
            ("recipient_lists", ["id"], False),
            ("sending_domains", ["domain"], False),
        ],
    )
    def test_source_response_shape(self, endpoint: str, expected_pk: list[str], expect_partition: bool) -> None:
        response = sparkpost_source(
            region="us",
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == "asc"
        if expect_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestPaginationAndResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_pagination_yields_and_saves_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls, params = _wire(
            session,
            [
                _response(
                    [{"event_id": "1", "timestamp": "2026-01-01T00:00:00.000Z"}],
                    links=[{"href": "/api/v1/events/message?cursor=p2", "rel": "next"}],
                ),
                _response([{"event_id": "2", "timestamp": "2026-01-01T00:01:00.000Z"}], links=[]),
            ],
        )
        manager = _make_manager()

        rows = _rows("events", manager)

        assert [r["event_id"] for r in rows] == ["1", "2"]
        # The first request opts into cursor pagination; the second follows the resolved next link.
        assert params[0]["cursor"] == "initial"
        assert params[0]["per_page"] == 10000
        assert urls[1] == "https://api.sparkpost.com/api/v1/events/message?cursor=p2"
        # State saved after the first batch (points at the next page); the empty-links page ends it.
        manager.save_state.assert_called_once_with(
            SparkPostResumeConfig(next_url="https://api.sparkpost.com/api/v1/events/message?cursor=p2")
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_results_terminates_without_saving(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], links=[{"href": "/api/v1/events/message?cursor=p2", "rel": "next"}])])
        manager = _make_manager()

        rows = _rows("events", manager)

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_endpoint_fetches_once(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_response([{"id": "t1"}, {"id": "t2"}])])
        manager = _make_manager()

        rows = _rows("templates", manager)

        assert [r["id"] for r in rows] == ["t1", "t2"]
        assert session.send.call_count == 1
        # A full-refresh, non-cursor endpoint sends no pagination or time-filter params.
        assert "cursor" not in params[0]
        assert "per_page" not in params[0]
        assert "from" not in params[0]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_events_incremental_uses_stored_watermark(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_response([{"event_id": "1"}], links=[])])
        manager = _make_manager()

        _rows(
            "events",
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, 12, 30, tzinfo=UTC),
        )

        assert params[0]["from"] == "2026-01-01T12:30"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_events_first_sync_seeds_lookback_window(self, MockSession: mock.MagicMock) -> None:
        # No stored watermark: ``from`` is seeded from the 10-day retention lookback rather than
        # falling back to SparkPost's default short window.
        session = MockSession.return_value
        _, params = _wire(session, [_response([{"event_id": "1"}], links=[])])

        _rows("events", _make_manager())

        assert "from" in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_never_sends_time_filter(self, MockSession: mock.MagicMock) -> None:
        # Even with incremental on, a full-refresh endpoint must not send a ``from`` filter.
        session = MockSession.return_value
        _, params = _wire(session, [_response([{"recipient": "a@b.co", "type": "transactional"}], links=[])])

        _rows(
            "suppression_list",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert "from" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_url(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls, params = _wire(session, [_response([{"event_id": "9"}], links=[])])
        manager = _make_manager(SparkPostResumeConfig(next_url="https://api.sparkpost.com/resume-here"))

        _rows("events", manager)

        # The resumed run starts at the saved next-page URL and drops the initial cursor params.
        assert urls[0] == "https://api.sparkpost.com/resume-here"
        assert params[0] == {}

    @pytest.mark.parametrize(
        "resume_url",
        [
            "https://evil.example.com/steal",
            "http://api.sparkpost.com/resume-here",
            "https://api.sparkpost.com.evil.com/resume-here",
        ],
    )
    def test_tampered_resume_url_is_rejected(self, resume_url: str) -> None:
        manager = _make_manager(SparkPostResumeConfig(next_url=resume_url))
        with pytest.raises(ValueError, match="unexpected URL"):
            sparkpost_source(
                region="us",
                api_key="key",
                endpoint="events",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
            )


def _msys(event: dict[str, Any], grouping: str = "message_event") -> dict[str, Any]:
    return {"msys": {grouping: event}}


def _batch_table(*batches: list[dict[str, Any]]) -> pa.Table:
    return pa.table({WEBHOOK_BATCH_KEY: [json.dumps(batch) for batch in batches]})


class TestWebhookTableTransformer:
    """SparkPost POSTs a batch of events per delivery, but a Hog function may only produce one
    payload per request — so the template hands over the whole batch and this transformer explodes
    it into the per-event rows the ``events`` table is built from."""

    def test_batch_is_exploded_into_one_row_per_event(self) -> None:
        table = _batch_table(
            [_msys({"event_id": "1", "type": "delivery", "timestamp": "1460989507"})],
            [
                _msys({"event_id": "2", "type": "open", "timestamp": "1460989600"}),
                _msys({"event_id": "3", "type": "click", "timestamp": "1460989700"}),
            ],
        )

        rows = _webhook_table_transformer(table).to_pylist()

        assert [row["event_id"] for row in rows] == ["1", "2", "3"]
        assert [row["type"] for row in rows] == ["delivery", "open", "click"]

    def test_repeated_event_id_within_a_batch_yields_one_row(self) -> None:
        # SparkPost delivers at least once, so a retried batch (or two S3 files read into the same
        # batch) can repeat an event. Delta merge only dedupes across syncs, so duplicates left in
        # here would seed multi-matching rows in the table.
        table = _batch_table(
            [_msys({"event_id": "1", "type": "delivery", "timestamp": "1460989507"})],
            [_msys({"event_id": "1", "type": "delivery", "timestamp": "1460989507"})],
        )

        rows = _webhook_table_transformer(table).to_pylist()

        assert len(rows) == 1
        assert rows[0]["event_id"] == "1"

    @pytest.mark.parametrize(
        ("pushed", "expected"),
        [
            # SparkPost pushes unix seconds; the Events Search API returns ISO 8601. `timestamp` is
            # both the incremental cursor and the datetime partition key, so an unconverted epoch
            # would drop pushed rows into the unknown-date partition and corrupt the watermark.
            ("1460989507", "2016-04-18T14:25:07.000Z"),
            (1460989507, "2016-04-18T14:25:07.000Z"),
            # A value already in the polled format is left alone.
            ("2016-04-18T14:25:07.000Z", "2016-04-18T14:25:07.000Z"),
        ],
    )
    def test_timestamp_is_restated_in_the_polled_format(self, pushed: Any, expected: str) -> None:
        table = _batch_table([_msys({"event_id": "1", "timestamp": pushed})])

        assert _webhook_table_transformer(table).to_pylist()[0]["timestamp"] == expected

    @pytest.mark.parametrize("grouping", ["relay_event", "ab_test_event"])
    def test_non_message_groupings_are_dropped(self, grouping: str) -> None:
        # Relay and A/B test events are a different shape that the Events Search API never returns,
        # so letting them through would pollute the table the poll path builds.
        table = _batch_table([_msys({"event_id": "1", "type": "relay_delivery"}, grouping=grouping)])

        assert _webhook_table_transformer(table).num_rows == 0

    @pytest.mark.parametrize(
        "batch",
        [
            # An event with no id can't be merged on the table's primary key.
            [{"msys": {"message_event": {"type": "delivery"}}}],
            # Shapes SparkPost shouldn't send, but which must not crash the sync.
            [{"msys": {}}],
            [{"not_msys": {"message_event": {"event_id": "1"}}}],
            ["not-an-object"],
            [],
        ],
    )
    def test_unusable_payloads_yield_no_rows(self, batch: Any) -> None:
        assert _webhook_table_transformer(_batch_table(batch)).num_rows == 0

    def test_unparseable_batch_is_skipped_without_losing_the_rest(self) -> None:
        table = pa.table(
            {
                WEBHOOK_BATCH_KEY: [
                    "{not json",
                    json.dumps([_msys({"event_id": "1", "timestamp": "1460989507"})]),
                ]
            }
        )

        rows = _webhook_table_transformer(table).to_pylist()

        assert [row["event_id"] for row in rows] == ["1"]


class TestWebhookItems:
    """The poll path must keep running until the webhook is live, and must hand over afterwards."""

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_poll_path_is_used_when_the_webhook_is_not_live(self, MockSession: mock.MagicMock) -> None:
        _wire(MockSession.return_value, [_response([{"event_id": "1"}], links=[])])
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=False)

        rows = _rows("events", _make_manager(), webhook_source_manager=webhook_manager)

        assert rows == [{"event_id": "1"}]
        webhook_manager.get_items.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_webhook_rows_are_read_with_the_dedup_transformer(self, MockSession: mock.MagicMock) -> None:
        _wire(MockSession.return_value, [_response([], links=[])])
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)

        sparkpost_source(
            region="us",
            api_key="key",
            endpoint="events",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
            webhook_source_manager=webhook_manager,
        ).items()

        webhook_manager.get_items.assert_called_once_with(table_transformer=_webhook_table_transformer)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_webhook_endpoints_never_consult_the_webhook_manager(self, MockSession: mock.MagicMock) -> None:
        # Only `events` has webhook coverage; the management lists must keep polling unconditionally.
        _wire(MockSession.return_value, [_response([{"id": "t1"}])])
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)

        rows = _rows("templates", _make_manager(), webhook_source_manager=webhook_manager)

        assert rows == [{"id": "t1"}]
        webhook_manager.webhook_enabled.assert_not_called()
        webhook_manager.get_items.assert_not_called()


def _json_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _webhook_object(**overrides: Any) -> dict[str, Any]:
    webhook = {
        "id": "wh_1",
        "name": "PostHog data warehouse",
        "target": WEBHOOK_URL,
        "events": ["delivery", "bounce"],
        "active": True,
    }
    webhook.update(overrides)
    return webhook


WEBHOOK_URL = "https://app.posthog.com/public/webhooks/abc"


class TestCreateWebhook:
    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_registers_a_webhook_authenticated_with_credentials_we_generate(self, MockSession: mock.MagicMock) -> None:
        # The whole safety story for the ingest endpoint rests on this: SparkPost signs nothing, so
        # if the registration ever stopped setting basic-auth credentials the endpoint would accept
        # anything the internet POSTs at it.
        session = MockSession.return_value
        session.post.return_value = _json_response({"results": {"id": "wh_1"}}, status_code=200)

        result = create_webhook("us", "key", WEBHOOK_URL)

        assert result.success is True
        url, kwargs = session.post.call_args[0][0], session.post.call_args[1]
        assert url == f"{HOST}/api/v1/webhooks"
        assert kwargs["json"]["target"] == WEBHOOK_URL
        assert kwargs["json"]["auth_type"] == "basic"

        credentials = kwargs["json"]["auth_credentials"]
        expected_header = (
            "Basic " + base64.b64encode(f"{credentials['username']}:{credentials['password']}".encode()).decode()
        )
        assert result.extra_inputs == {"authorization_header": expected_header}

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_generated_password_is_not_reused_between_registrations(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        session.post.return_value = _json_response({"results": {"id": "wh_1"}})

        first = create_webhook("us", "key", WEBHOOK_URL)
        second = create_webhook("us", "key", WEBHOOK_URL)

        assert first.extra_inputs["authorization_header"] != second.extra_inputs["authorization_header"]

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_subscribes_to_the_events_the_search_api_also_returns(self, MockSession: mock.MagicMock) -> None:
        # Subscribing to relay or A/B test events would push differently-shaped rows into the table
        # the poll path builds.
        session = MockSession.return_value
        session.post.return_value = _json_response({"results": {"id": "wh_1"}})

        create_webhook("us", "key", WEBHOOK_URL)

        events = session.post.call_args[1]["json"]["events"]
        assert events == WEBHOOK_EVENT_TYPES
        assert not [event for event in events if event.startswith("relay_") or event.startswith("ab_test")]

    @mock.patch(SPARKPOST_SESSION_PATCH)
    @pytest.mark.parametrize(
        ("status_code", "expected_fragment"),
        [
            (401, "Webhooks: Read/Write"),
            (403, "Webhooks: Read/Write"),
            (500, "HTTP 500"),
        ],
    )
    def test_rejected_registration_reports_an_actionable_error(
        self, MockSession: mock.MagicMock, status_code: int, expected_fragment: str
    ) -> None:
        MockSession.return_value.post.return_value = _json_response({}, status_code=status_code)

        result = create_webhook("us", "key", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None
        assert expected_fragment in result.error
        # A failed registration must not hand back credentials the template would then trust.
        assert result.extra_inputs == {}

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_unreachable_api_is_reported_not_raised(self, MockSession: mock.MagicMock) -> None:
        MockSession.return_value.post.side_effect = requests.ConnectionError("boom")

        result = create_webhook("us", "key", WEBHOOK_URL)

        assert result.success is False
        assert result.extra_inputs == {}

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_registers_against_the_selected_region(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        session.post.return_value = _json_response({"results": {"id": "wh_1"}})

        create_webhook("eu", "key", WEBHOOK_URL)

        assert session.post.call_args[0][0] == "https://api.eu.sparkpost.com/api/v1/webhooks"


class TestExternalWebhookInfo:
    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_reports_the_webhook_targeting_our_url(self, MockSession: mock.MagicMock) -> None:
        MockSession.return_value.get.return_value = _json_response(
            {"results": [_webhook_object(target="https://elsewhere.example/hook"), _webhook_object()]}
        )

        info = get_external_webhook_info("us", "key", WEBHOOK_URL)

        assert info.exists is True
        assert info.url == WEBHOOK_URL
        assert info.enabled_events == ["delivery", "bounce"]
        assert info.status == "enabled"

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_disabled_webhook_is_reported_as_disabled(self, MockSession: mock.MagicMock) -> None:
        MockSession.return_value.get.return_value = _json_response({"results": [_webhook_object(active=False)]})

        assert get_external_webhook_info("us", "key", WEBHOOK_URL).status == "disabled"

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_no_matching_webhook_reports_absent(self, MockSession: mock.MagicMock) -> None:
        MockSession.return_value.get.return_value = _json_response(
            {"results": [_webhook_object(target="https://elsewhere.example/hook")]}
        )

        assert get_external_webhook_info("us", "key", WEBHOOK_URL).exists is False

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_api_failure_is_surfaced_not_raised(self, MockSession: mock.MagicMock) -> None:
        MockSession.return_value.get.return_value = _json_response({}, status_code=403)

        info = get_external_webhook_info("us", "key", WEBHOOK_URL)

        assert info.exists is False
        assert info.error is not None


class TestSyncWebhookEvents:
    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_missing_events_are_added_without_removing_existing_ones(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        session.get.return_value = _json_response({"results": [_webhook_object(events=["delivery", "relay_delivery"])]})
        session.put.return_value = _json_response({"results": {"message": "Updated"}})

        result = sync_webhook_events("us", "key", WEBHOOK_URL, ["delivery", "open"])

        assert result.success is True
        assert session.put.call_args[0][0] == f"{HOST}/api/v1/webhooks/wh_1"
        # A manually broadened webhook keeps the extra event it was given.
        assert session.put.call_args[1]["json"] == {"events": ["delivery", "open", "relay_delivery"]}

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_no_write_when_every_desired_event_is_already_subscribed(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        session.get.return_value = _json_response({"results": [_webhook_object(events=["delivery", "open"])]})

        assert sync_webhook_events("us", "key", WEBHOOK_URL, ["open", "delivery"]).success is True
        session.put.assert_not_called()

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_failure_is_reported_not_raised(self, MockSession: mock.MagicMock) -> None:
        MockSession.return_value.get.side_effect = requests.ConnectionError("boom")

        assert sync_webhook_events("us", "key", WEBHOOK_URL, ["open"]).success is False


class TestDeleteWebhook:
    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_only_deletes_webhooks_pointing_at_our_url(self, MockSession: mock.MagicMock) -> None:
        # The account's own webhooks live alongside ours; deleting by anything looser than an exact
        # target match would tear down the customer's integrations.
        session = MockSession.return_value
        session.get.return_value = _json_response(
            {
                "results": [
                    _webhook_object(id="wh_theirs", target="https://elsewhere.example/hook"),
                    _webhook_object(id="wh_ours"),
                ]
            }
        )
        session.delete.return_value = _json_response({"results": {"message": "Deleted"}}, status_code=200)

        result = delete_webhook("us", "key", WEBHOOK_URL)

        assert result.success is True
        assert [call[0][0] for call in session.delete.call_args_list] == [f"{HOST}/api/v1/webhooks/wh_ours"]

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_nothing_to_delete_is_a_success(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        session.get.return_value = _json_response({"results": []})

        assert delete_webhook("us", "key", WEBHOOK_URL).success is True
        session.delete.assert_not_called()

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_rejected_delete_is_reported(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        session.get.return_value = _json_response({"results": [_webhook_object()]})
        session.delete.return_value = _json_response({}, status_code=403)

        result = delete_webhook("us", "key", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "wh_1" in result.error
