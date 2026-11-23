from datetime import datetime, timedelta
from typing import Any

import pytest
import time_machine

import requests

from products.warehouse_sources.sources.freshchat._config import FreshchatSourceConfig
from products.warehouse_sources.sources.freshchat.freshchat import (
    FreshchatHostNotAllowedError,
    FreshchatResumeConfig,
    historical_metric_rows,
    validate_credentials,
)
from products.warehouse_sources.sources.freshchat.settings import (
    HISTORICAL_METRICS,
    PER_PAGE,
    USERS_CREATED_FROM,
    HistoricalMetric,
)
from products.warehouse_sources.sources.freshchat.source import FreshchatSource
from products.warehouse_sources.sources.sdk import RESTClientNonRetryableError
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)

BASE_HOST = "acme.freshchat.com"

# What a Freshworks portal domain answers with on these paths: the web app, not the API.
HTML_BODY = b"<!DOCTYPE html><html><head><title>Freshworks</title></head><body></body></html>"


def _page(data_key: str, items: list[dict[str, Any]], current: int, total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            data_key: items,
            "pagination": {"current_page": current, "total_pages": total_pages, "total_items": 999},
        }
    )


def _driver(domain: str = BASE_HOST, api_key: str = "key") -> SourceDriver:
    return SourceDriver(FreshchatSource(), FreshchatSourceConfig(domain=domain, api_key=api_key))


class TestGetRows:
    def test_paginates_by_page_number_and_saves_state(self) -> None:
        result = _driver().run(
            "agents",
            [
                _page("agents", [{"id": 1}], current=1, total_pages=2),
                _page("agents", [{"id": 2}], current=2, total_pages=2),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}]
        # The API reports total_pages=2, so it stops right after page 2 — no extra empty request.
        assert len(result.requests) == 2
        assert result.params("page") == ["1", "2"]
        assert result.params("items_per_page") == [str(PER_PAGE), str(PER_PAGE)]
        # State saved once, pointing at page 2 (the next page after the first was written).
        assert result.saved_states == [FreshchatResumeConfig(page=2)]

    def test_outbound_messages_is_one_unpaginated_request(self) -> None:
        # The endpoint documents no paging and returns every message at once. Page params would
        # make the paginator re-request the same array until it hit an empty page that never comes.
        messages = [
            {"message_id": "m1", "request_id": "r1", "status": "Delivered", "created_on": 1700000000},
            {"message_id": "m2", "request_id": "r1", "status": "Failed", "failure_code": "OBM001"},
        ]
        result = _driver().run("outbound_messages", [ScriptedResponse(json={"outbound_messages": messages})])

        assert result.raised is None
        assert result.rows == messages
        assert len(result.requests) == 1
        assert result.requests[0].path == "/v2/outbound-messages"
        assert result.requests[0].query == {}
        assert result.saved_states == []

    def test_bearer_token_is_redacted_from_samples(self) -> None:
        # The token rides in the Authorization header; it must be value-redacted from captured
        # HTTP samples via the tracked session's redact_values.
        result = _driver(api_key="secret-key").run("agents", [_page("agents", [{"id": 1}], 1, 1)])

        assert result.raised is None
        assert "secret-key" in result.session_options[0].get("redact_values", ())

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    def test_non_retryable_status_raises(self, status_code: int) -> None:
        result = _driver().run("agents", [ScriptedResponse(status=status_code, json={"error": "boom"})])

        assert isinstance(result.raised, requests.HTTPError)

    def test_html_body_raises_the_mapped_non_retryable_error(self) -> None:
        # A domain that serves the web app answers 200 with HTML. That must fail the table once with
        # the message the source maps, not retry a body that can never parse.
        result = _driver().run("agents", [ScriptedResponse(body=HTML_BODY)])

        assert isinstance(result.raised, RESTClientNonRetryableError)
        assert str(result.raised).startswith("Non-JSON response from")
        assert len(result.requests) == 1

    def test_disallowed_host_raises_before_any_request(self) -> None:
        # A saved-then-edited domain must never receive the stored token at sync time (SSRF).
        result = _driver(domain="metadata.google.internal").run("agents", [])

        assert isinstance(result.raised, FreshchatHostNotAllowedError)
        assert result.requests == []

    def test_redirect_response_raises_and_is_not_followed(self) -> None:
        # A 3xx from the allowed host could point anywhere; following it would defeat the host
        # allowlist, so it must surface as a hard error instead.
        result = _driver().run(
            "agents", [ScriptedResponse(status=302, headers={"Location": "http://169.254.169.254/"})]
        )

        assert isinstance(result.raised, ValueError)
        assert len(result.requests) == 1


class TestFanout:
    """Freshchat exposes no top-level conversations list, so both conversation tables are reached
    by fanning out from Users."""

    def test_user_conversations_carries_the_parent_user_id(self) -> None:
        result = _driver().run(
            "user_conversations",
            route(
                {
                    "/v2/users": [_page("users", [{"id": "u1"}, {"id": "u2"}], current=1, total_pages=1)],
                    "/v2/users/u1/conversations": [ScriptedResponse(json={"conversations": [{"id": "c1"}]})],
                    "/v2/users/u2/conversations": [
                        ScriptedResponse(json={"conversations": [{"id": "c2"}, {"id": "c3"}]})
                    ],
                }
            ),
        )

        assert result.raised is None
        # A conversation can be listed under more than one user, so the row has to name its parent
        # — the primary key is (user_id, id).
        assert result.rows == [
            {"id": "c1", "user_id": "u1"},
            {"id": "c2", "user_id": "u2"},
            {"id": "c3", "user_id": "u2"},
        ]
        assert result.requests[0].param("created_from") == USERS_CREATED_FROM
        # The child endpoint documents no query params; sending page-size or sort params there
        # would be undocumented guesswork.
        assert result.requests[1].query == {}

    def test_conversation_messages_is_not_resumable(self) -> None:
        result = _driver().run(
            "conversation_messages",
            [_page("users", [], current=1, total_pages=1)],
            resume_state=FreshchatResumeConfig(page=2),
        )

        assert result.response is not None
        assert result.response.supports_resume is False


def _metric_answer(request: RecordedRequest) -> ScriptedResponse:
    # One daily bucket at the start of each requested window.
    metric = request.param("metric")
    start = request.param("start")
    return ScriptedResponse(
        json={
            "metrics": [metric],
            "start": start,
            "end": request.param("end"),
            "interval": "1d",
            "data": [
                {
                    "groupings": [],
                    "series": [{"start": start, "end": "bucket-end", "values": [{"key": metric, "value": "2"}]}],
                }
            ],
        }
    )


class TestHistoricalMetrics:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Any:
        with time_machine.travel("2026-03-15T12:00:00Z", tick=False):
            yield

    @pytest.mark.parametrize(
        "inputs, first_start, window_count",
        [
            ({}, "2025-03-15T00:00:00.000Z", 13),
            # After midnight the cursor is today's bucket, but yesterday's bucket can still change.
            (
                {"incremental_field": "interval_start", "db_incremental_field_last_value": "2026-03-15T00:00:00.000Z"},
                "2026-03-14T00:00:00.000Z",
                1,
            ),
            (
                {"incremental_field": "interval_start", "db_incremental_field_last_value": "2026-01-20T00:00:00.000Z"},
                "2026-01-19T00:00:00.000Z",
                2,
            ),
        ],
    )
    def test_requests_each_metric_over_contiguous_windows(
        self, inputs: dict[str, Any], first_start: str, window_count: int
    ) -> None:
        result = _driver().run("historical_metrics", _metric_answer, **inputs)

        assert result.raised is None
        assert len(result.requests) == len(HISTORICAL_METRICS) * window_count
        aggregators = {metric.name: metric.aggregator for metric in HISTORICAL_METRICS}
        for request in result.requests:
            assert request.path == "/v2/metrics/historical"
            assert request.param("interval") == "1d"
            assert request.param("aggregator") == aggregators[request.param("metric") or ""]

        first_metric = [r for r in result.requests if r.param("metric") == HISTORICAL_METRICS[0].name]
        assert first_metric[0].param("start") == first_start
        assert first_metric[-1].param("end") == "2026-03-15T12:00:00.000Z"
        for previous, following in zip(first_metric, first_metric[1:]):
            previous_end = datetime.fromisoformat(previous.param("end") or "")
            assert datetime.fromisoformat(following.param("start") or "") - previous_end == timedelta(milliseconds=1)

    def test_yields_one_row_per_metric_bucket_without_claiming_order(self) -> None:
        result = _driver().run(
            "historical_metrics",
            _metric_answer,
            incremental_field="interval_start",
            db_incremental_field_last_value="2026-03-10T00:00:00.000Z",
        )

        assert result.raised is None
        assert result.rows[0] == {
            "metric": HISTORICAL_METRICS[0].name,
            "grouping": "",
            "aggregator": HISTORICAL_METRICS[0].aggregator,
            "granularity": "1d",
            "interval_start": "2026-03-09T00:00:00.000Z",
            "interval_end": "bucket-end",
            "value": 2.0,
        }
        assert len(result.rows) == len(HISTORICAL_METRICS)
        assert result.response is not None
        assert result.response.sort_mode is None
        assert result.response.supports_resume is False

    @pytest.mark.parametrize(
        "body, expected",
        [
            (None, []),
            ({"data": None}, []),
            ({"data": ["junk", {"series": None}]}, []),
            (
                {
                    "data": [
                        {
                            "groupings": [{"key": "group", "value": "g1"}, {"key": "agent", "value": "a1"}],
                            "series": [
                                {
                                    "start": "s",
                                    "end": "e",
                                    "values": [
                                        {"key": "csat_metrics.count_per_rating", "value": "4.5"},
                                        {"key": "csat_metrics.rating", "value": ""},
                                        {"value": "1"},
                                        "junk",
                                    ],
                                }
                            ],
                        }
                    ]
                },
                [
                    {
                        "grouping": '[["agent","a1"],["group","g1"]]',
                        "metric": "csat_metrics.count_per_rating",
                        "value": 4.5,
                    },
                    {"grouping": '[["agent","a1"],["group","g1"]]', "metric": "csat_metrics.rating", "value": None},
                ],
            ),
            (
                {
                    "data": [
                        {
                            "groupings": [{"key": "group", "value": "g1,agent=a1"}],
                            "series": [{"start": "s", "end": "e", "values": [{"value": "3"}]}],
                        },
                        {
                            "groupings": [{"key": "agent", "value": "a1"}, {"key": "group", "value": "g1"}],
                            "series": [{"start": "s", "end": "e", "values": [{"value": "n/a"}]}],
                        },
                    ]
                },
                [
                    {"grouping": '[["group","g1,agent=a1"]]', "metric": "requested.metric", "value": 3.0},
                    {"grouping": '[["agent","a1"],["group","g1"]]', "metric": "requested.metric", "value": None},
                ],
            ),
        ],
    )
    def test_flattens_metric_series(self, body: Any, expected: list[dict[str, Any]]) -> None:
        rows = historical_metric_rows(body, HistoricalMetric("requested.metric", aggregator="avg"))

        assert [{key: row[key] for key in ("grouping", "metric", "value")} for row in rows] == expected


class TestValidateCredentials:
    # A Freshworks portal domain answers the probe with its web app, not the API. An empty body and
    # a truncated body stay acceptable, because the sync path reads an empty 2xx as an empty page
    # and retries a truncated one, rather than calling either a broken host.
    @pytest.mark.parametrize(
        "body, returned_json",
        [(HTML_BODY, False), (b"", True), (b'{"configuration": {"app_id"', True)],
    )
    def test_probe_reports_whether_the_body_is_json(self, body: bytes, returned_json: bool) -> None:
        with scripted_network([ScriptedResponse(body=body)]) as network:
            assert validate_credentials(BASE_HOST, "key") == (200, returned_json)

        assert network.requests_log[0].path == "/v2/accounts/configuration"

    def test_session_redacts_api_key_from_samples(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials(BASE_HOST, "secret-key")

        assert network.session_options[0].get("redact_values") == ("secret-key",)

    def test_probe_disables_redirects_to_protect_token(self) -> None:
        # The token rides on the probe; the session must be built with redirects pinned off so a
        # redirect can't replay it to the redirect target during validation.
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials(BASE_HOST, "key")

        assert network.session_options[0].get("allow_redirects") is False
