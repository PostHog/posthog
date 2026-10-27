import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import pyarrow as pa
import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sparkpost import (
    SparkPostSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import WEBHOOK_BATCH_KEY
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source import SparkPostSource
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.sparkpost import (
    SparkPostLinksPaginator,
    SparkPostResumeConfig,
    _format_from,
    _webhook_table_transformer,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    sync_webhook_events,
    validate_credentials,
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


def _page(results: Any, links: Any = None) -> ScriptedResponse:
    body: dict[str, Any] = {"results": results}
    if links is not None:
        body["links"] = links
    return ScriptedResponse(json=body)


def _run(
    endpoint: str,
    script: Script,
    resume_state: SparkPostResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    config = SparkPostSourceConfig(api_key="key", region="us")
    return SourceDriver(SparkPostSource(), config).run(endpoint, script, resume_state=resume_state, **inputs)


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


class TestLinksPaginator:
    """The cursor paginator that walks SparkPost's ``links: [{href, rel}]`` next link, resolving a
    relative href against the host and re-pinning it there (SSRF guard)."""

    def _next_url(self, links: Any, data: Any = None) -> str | None:
        rows = data if data is not None else [{"event_id": "1"}]
        paginator = SparkPostLinksPaginator(HOST)
        paginator.update_state(_response(rows, links=links), rows)
        return paginator._next_url if paginator.has_next_page else None

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
            # 403 = genuine key without the Account scope used by the probe; don't block connecting.
            (403, True),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            is_valid, error = validate_credentials("us", "key")

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None


class TestPaginationAndResume:
    def test_cursor_pagination_yields_and_saves_state(self) -> None:
        result = _run(
            "events",
            [
                _page(
                    [{"event_id": "1", "timestamp": "2026-01-01T00:00:00.000Z"}],
                    links=[{"href": "/api/v1/events/message?cursor=p2", "rel": "next"}],
                ),
                _page([{"event_id": "2", "timestamp": "2026-01-01T00:01:00.000Z"}], links=[]),
            ],
        )

        assert [r["event_id"] for r in result.rows] == ["1", "2"]
        # The first request opts into cursor pagination; the second follows the resolved next link.
        assert result.requests[0].param("cursor") == "initial"
        assert result.requests[0].param("per_page") == "10000"
        assert result.urls[1] == "https://api.sparkpost.com/api/v1/events/message?cursor=p2"
        # State saved after the first batch (points at the next page); the empty-links page ends it.
        assert result.saved_states == [
            SparkPostResumeConfig(next_url="https://api.sparkpost.com/api/v1/events/message?cursor=p2")
        ]

    def test_events_incremental_uses_stored_watermark(self) -> None:
        result = _run(
            "events",
            [_page([{"event_id": "1"}], links=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, 12, 30, tzinfo=UTC),
        )

        assert result.requests[0].param("from") == "2026-01-01T12:30"

    def test_full_refresh_endpoint_never_sends_time_filter(self) -> None:
        # Even with incremental on, a full-refresh endpoint must not send a ``from`` filter.
        result = _run(
            "suppression_list",
            [_page([{"recipient": "a@b.co", "type": "transactional"}], links=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.requests[0].param("from") is None

    def test_resumes_from_saved_url(self) -> None:
        result = _run(
            "events",
            [_page([{"event_id": "9"}], links=[])],
            resume_state=SparkPostResumeConfig(next_url="https://api.sparkpost.com/resume-here"),
        )

        # The resumed run starts at the saved next-page URL and drops the initial cursor params.
        assert result.urls[0] == "https://api.sparkpost.com/resume-here"
        assert dict(result.requests[0].query) == {}

    @pytest.mark.parametrize(
        "resume_url",
        [
            "https://evil.example.com/steal",
            "http://api.sparkpost.com/resume-here",
            "https://api.sparkpost.com.evil.com/resume-here",
        ],
    )
    def test_tampered_resume_url_is_rejected(self, resume_url: str) -> None:
        result = _run("events", [], resume_state=SparkPostResumeConfig(next_url=resume_url))

        assert isinstance(result.raised, ValueError)
        assert "unexpected URL" in str(result.raised)
        assert result.requests == []


def _msys(event: dict[str, Any], grouping: str = "message_event") -> dict[str, Any]:
    return {"msys": {grouping: event}}


def _batch_table(*batches: list[dict[str, Any]]) -> pa.Table:
    return pa.table({WEBHOOK_BATCH_KEY: [json.dumps(batch) for batch in batches]})


class TestWebhookTableTransformer:
    """SparkPost POSTs a batch of events per delivery, but a Hog function may only produce one
    payload per request — so the template hands over the whole batch and this transformer explodes
    it into the per-event rows the ``events`` table is built from."""

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

    def test_webhook_rows_are_read_with_the_dedup_transformer(self) -> None:
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)

        with mock.patch.object(SparkPostSource, "get_webhook_source_manager", return_value=webhook_manager):
            _run("events", [_page([], links=[])])

        webhook_manager.get_items.assert_called_once_with(table_transformer=_webhook_table_transformer)

    def test_non_webhook_endpoints_never_consult_the_webhook_manager(self) -> None:
        # Only `events` has webhook coverage; the management lists must keep polling unconditionally.
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)

        with mock.patch.object(SparkPostSource, "get_webhook_source_manager", return_value=webhook_manager):
            result = _run("templates", [_page([{"id": "t1"}])])

        assert result.rows == [{"id": "t1"}]
        webhook_manager.webhook_enabled.assert_not_called()
        webhook_manager.get_items.assert_not_called()


def _json_response(body: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


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


def _by_method(answers: dict[str, ScriptedResponse]) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        return answers[request.method]

    return respond


class TestCreateWebhook:
    def test_generated_password_is_not_reused_between_registrations(self) -> None:
        with scripted_network(always(_json_response({"results": {"id": "wh_1"}}))):
            first = create_webhook("us", "key", WEBHOOK_URL)
            second = create_webhook("us", "key", WEBHOOK_URL)

        assert first.extra_inputs["authorization_header"] != second.extra_inputs["authorization_header"]

    @pytest.mark.parametrize(
        ("status_code", "expected_fragment"),
        [
            (401, "Webhooks: Read/Write"),
            (403, "Webhooks: Read/Write"),
            (500, "HTTP 500"),
        ],
    )
    def test_rejected_registration_reports_an_actionable_error(self, status_code: int, expected_fragment: str) -> None:
        with scripted_network(always(_json_response({}, status_code=status_code))):
            result = create_webhook("us", "key", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None
        assert expected_fragment in result.error
        # A failed registration must not hand back credentials the template would then trust.
        assert result.extra_inputs == {}

    def test_unreachable_api_is_reported_not_raised(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))):
            result = create_webhook("us", "key", WEBHOOK_URL)

        assert result.success is False
        assert result.extra_inputs == {}


class TestExternalWebhookInfo:
    def test_disabled_webhook_is_reported_as_disabled(self) -> None:
        with scripted_network([_json_response({"results": [_webhook_object(active=False)]})]):
            assert get_external_webhook_info("us", "key", WEBHOOK_URL).status == "disabled"

    def test_no_matching_webhook_reports_absent(self) -> None:
        script = [_json_response({"results": [_webhook_object(target="https://elsewhere.example/hook")]})]
        with scripted_network(script):
            assert get_external_webhook_info("us", "key", WEBHOOK_URL).exists is False

    def test_api_failure_is_surfaced_not_raised(self) -> None:
        with scripted_network([_json_response({}, status_code=403)]):
            info = get_external_webhook_info("us", "key", WEBHOOK_URL)

        assert info.exists is False
        assert info.error is not None


class TestSyncWebhookEvents:
    def test_missing_events_are_added_without_removing_existing_ones(self) -> None:
        script = _by_method(
            {
                "GET": _json_response({"results": [_webhook_object(events=["delivery", "relay_delivery"])]}),
                "PUT": _json_response({"results": {"message": "Updated"}}),
            }
        )
        with scripted_network(script) as network:
            result = sync_webhook_events("us", "key", WEBHOOK_URL, ["delivery", "open"])

        assert result.success is True
        put = next(request for request in network.requests_log if request.method == "PUT")
        assert put.url == f"{HOST}/api/v1/webhooks/wh_1"
        # A manually broadened webhook keeps the extra event it was given.
        assert put.json() == {"events": ["delivery", "open", "relay_delivery"]}

    def test_no_write_when_every_desired_event_is_already_subscribed(self) -> None:
        script = [_json_response({"results": [_webhook_object(events=["delivery", "open"])]})]
        with scripted_network(script) as network:
            assert sync_webhook_events("us", "key", WEBHOOK_URL, ["open", "delivery"]).success is True

        assert [request.method for request in network.requests_log] == ["GET"]

    def test_failure_is_reported_not_raised(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))):
            assert sync_webhook_events("us", "key", WEBHOOK_URL, ["open"]).success is False


class TestDeleteWebhook:
    def test_nothing_to_delete_is_a_success(self) -> None:
        with scripted_network([_json_response({"results": []})]) as network:
            assert delete_webhook("us", "key", WEBHOOK_URL).success is True

        assert [request.method for request in network.requests_log] == ["GET"]

    def test_rejected_delete_is_reported(self) -> None:
        script = _by_method(
            {
                "GET": _json_response({"results": [_webhook_object()]}),
                "DELETE": _json_response({}, status_code=403),
            }
        )
        with scripted_network(script):
            result = delete_webhook("us", "key", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "wh_1" in result.error
