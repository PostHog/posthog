from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailersend import (
    MailerSendSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.mailersend import (
    MAILERSEND_ANALYTICS_EVENTS,
    MailerSendResumeConfig,
    _date_window,
    _to_datetime,
    check_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.settings import MAILERSEND_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.source import MailerSendSource

BASE = "https://api.mailersend.com/v1"


def _driver() -> SourceDriver:
    return SourceDriver(MailerSendSource(), MailerSendSourceConfig(api_token="mlsn.token"))


def _page(items: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "links": {"next": next_url}})


class TestToDatetime:
    @parameterized.expand(
        [
            (
                "aware_datetime",
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            ),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)),
            ("date_value", date(2026, 3, 4), datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)),
            ("unix_int", 1443651141, datetime(2015, 9, 30, 22, 12, 21, tzinfo=UTC)),
            ("iso_z_suffix", "2021-08-31T13:43:35.000000Z", datetime(2021, 8, 31, 13, 43, 35, tzinfo=UTC)),
            ("iso_offset", "2021-08-31T13:43:35+00:00", datetime(2021, 8, 31, 13, 43, 35, tzinfo=UTC)),
        ]
    )
    def test_to_datetime(self, _name: str, value: Any, expected: datetime) -> None:
        assert _to_datetime(value) == expected


class TestActivityDateWindow:
    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_future_cursor_is_clamped_below_date_to(self) -> None:
        # A future-dated cursor would make date_from >= date_to and 422 the request; it must be clamped.
        future = datetime(2027, 1, 1, tzinfo=UTC)
        window = _date_window(
            should_use_incremental_field=True, db_incremental_field_last_value=future, lookback_days=30
        )
        assert window.start < window.end


class TestCheckCredentials:
    @pytest.mark.parametrize(
        ("status_code", "schema_name", "expected_ok"),
        [
            (200, None, True),
            (401, None, False),
            (403, None, True),  # valid token, missing scope — accepted at source-create
            (403, "activity", False),  # scope gap surfaced for a specific schema
            (500, None, False),
        ],
    )
    def test_status_mapping(self, status_code: int, schema_name: str | None, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            ok, _error = check_credentials("mlsn.token", schema_name)

        assert ok is expected_ok
        assert {request.path for request in network.requests_log} == {"/v1/domains"}
        assert network.requests_log[0].param("limit") == "10"
        assert network.requests_log[0].headers["authorization"] == "Bearer mlsn.token"

    def test_network_error_is_not_valid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            ok, error = check_credentials("mlsn.token")

        assert ok is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/v1/domains"}


class TestTopLevelPagination:
    @parameterized.expand(
        [
            ("last_allowed_page_is_followed", 1000, 2, ["r1", "r2"]),
            ("page_past_the_cap_ends_the_table", 1001, 1, ["r1"]),
        ]
    )
    def test_stops_at_the_documented_page_cap(
        self,
        _name: str,
        next_page: int,
        expected_requests: int,
        expected_ids: list[str],
    ) -> None:
        # MailerSend accepts pages 1-1000 and rejects page 1001 with a 422, but still advertises a
        # next link on page 1000, so the cap has to end the table instead of following that link.
        result = _driver().run(
            "recipients",
            [
                _page([{"id": "r1"}], next_url=f"{BASE}/recipients?page={next_page}&limit=100"),
                _page([{"id": "r2"}], next_url=None),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == expected_ids
        assert len(result.requests) == expected_requests
        assert result.params("page") == ([None, "1000"] if next_page == 1000 else [None])

    def test_offhost_links_next_rejected_before_send(self) -> None:
        # `links.next` is followed verbatim, so an off-host value must be rejected by the client's
        # host pin before the Bearer token can be replayed to an attacker-controlled host.
        result = _driver().run(
            "recipients",
            [
                _page([{"id": "r1"}], next_url="https://evil.example/v1/recipients?page=2"),
                _page([{"id": "r2"}], next_url=None),
            ],
        )

        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)

        # Only the on-host first page went out; the off-host next link never reached the network.
        assert result.paths == ["/v1/recipients"]


class TestActivityFanOut:
    @staticmethod
    def _domains(*ids: str) -> ScriptedResponse:
        return _page([{"id": i} for i in ids], next_url=None)

    def test_resumes_from_saved_domain(self) -> None:
        # State marking d1 complete must skip it and only fetch d2.
        result = _driver().run(
            "activity",
            [self._domains("d1", "d2"), _page([{"id": "a2"}], next_url=None)],
            resume_state=MailerSendResumeConfig(
                fanout_state={"completed": ["/activity/d1"], "current": None, "child_state": None}
            ),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a2"]
        assert [request.url.split("?", 1)[0] for request in result.requests if "/activity/" in request.path] == [
            f"{BASE}/activity/d2"
        ]

    @staticmethod
    def _rejected_window() -> ScriptedResponse:
        # MailerSend rejects a window reaching past the account's activity retention.
        return ScriptedResponse(status=422, json={"message": "The given data was invalid."})

    @staticmethod
    def _window_days(request: RecordedRequest) -> float:
        date_from = request.param("date_from")
        date_to = request.param("date_to")
        assert date_from is not None and date_to is not None
        return (int(date_to) - int(date_from)) / (24 * 60 * 60)

    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_narrows_the_window_when_the_account_retains_less(self) -> None:
        # Activity retention is 30, 7 or 1 days depending on the plan and no endpoint reports it,
        # so a rejected window must step down a tier rather than fail the whole sync.
        result = _driver().run(
            "activity",
            [
                self._domains("d1"),
                self._rejected_window(),
                self._domains("d1"),
                _page([{"id": "a1"}], next_url=None),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a1"]
        attempts = [request for request in result.requests if "/activity/" in request.path]
        assert [self._window_days(request) for request in attempts] == [30, 7]

    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_every_tier_rejected_fails_the_sync(self) -> None:
        result = _driver().run(
            "activity",
            [
                self._domains("d1"),
                self._rejected_window(),
                self._domains("d1"),
                self._rejected_window(),
                self._domains("d1"),
                self._rejected_window(),
            ],
        )

        assert isinstance(result.raised, HTTPError)
        attempts = [request for request in result.requests if "/activity/" in request.path]
        assert [self._window_days(request) for request in attempts] == [30, 7, 1]


class TestAnalyticsByDate:
    @parameterized.expand(
        [
            ("full_refresh_backfills_retention", False, None, datetime(2025, 12, 25, tzinfo=UTC)),
            (
                "incremental_rereads_last_synced_day",
                True,
                datetime(2026, 6, 20, tzinfo=UTC),
                datetime(2026, 6, 20, tzinfo=UTC),
            ),
        ]
    )
    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_request_window_and_row_shape(
        self,
        _name: str,
        should_use_incremental_field: bool,
        last_value: datetime | None,
        expected_date_from: datetime,
    ) -> None:
        result = _driver().run(
            "analytics_by_date",
            [
                ScriptedResponse(
                    json={
                        "data": {
                            "date_from": "1782172800",
                            "date_to": "1782259199",
                            "group_by": "days",
                            "stats": [{"date": "1782172800", "sent": 4, "opened": 2}],
                        }
                    }
                )
            ],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.rows == [{"date": datetime(2026, 6, 23, tzinfo=UTC), "sent": 4, "opened": 2}]
        assert len(result.requests) == 1
        request = result.requests[0]
        assert request.origin + request.path == f"{BASE}/analytics/date"
        assert request.param("date_from") == str(int(expected_date_from.timestamp()))
        assert request.param("date_to") == str(int(datetime(2026, 6, 23, tzinfo=UTC).timestamp()))
        assert request.param("group_by") == "days"
        assert request.query["event[]"] == tuple(MAILERSEND_ANALYTICS_EVENTS)


class TestLegacyResumeStateCompat:
    def test_legacy_state_shape_still_deserializes(self) -> None:
        # Resume state saved by the pre-migration source (next_page/domain_id only) must still parse.
        state = MailerSendResumeConfig(next_page=3, domain_id="d2")
        assert state.next_page == 3
        assert state.domain_id == "d2"
        assert state.fanout_state is None


class TestSourceResponseShape:
    @staticmethod
    def _response(endpoint: str) -> SourceResponse:
        body: dict[str, Any] = {"data": {"stats": []}} if endpoint == "analytics_by_date" else {"data": []}
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])
        assert result.raised is None
        assert result.response is not None
        return result.response

    @parameterized.expand(
        [
            "domains",
            "recipients",
            "templates",
            "messages",
            "activity",
            "hard_bounces",
            "spam_complaints",
            "unsubscribes",
            "analytics_by_date",
        ]
    )
    def test_primary_keys_match_settings(self, endpoint: str) -> None:
        resource = self._response(endpoint)
        assert resource.name == endpoint
        assert resource.primary_keys == MAILERSEND_ENDPOINTS[endpoint].primary_keys

    def test_activity_primary_key_includes_domain_id(self) -> None:
        # Activity ids are only unique within a domain, so the table-wide key must include domain_id.
        assert MAILERSEND_ENDPOINTS["activity"].primary_keys == ["domain_id", "id"]

    @parameterized.expand([("activity", "desc"), ("domains", "asc")])
    def test_sort_mode(self, endpoint: str, expected_sort: str) -> None:
        assert self._response(endpoint).sort_mode == expected_sort

    @parameterized.expand(
        [
            ("domains", "created_at"),
            ("recipients", "created_at"),
            ("templates", "created_at"),
            ("messages", "created_at"),
            ("activity", "created_at"),
            ("hard_bounces", "created_at"),
            ("spam_complaints", "created_at"),
            ("unsubscribes", "created_at"),
            ("analytics_by_date", "date"),
        ]
    )
    def test_partitions_on_a_stable_timestamp(self, endpoint: str, expected_key: str) -> None:
        resource = self._response(endpoint)
        assert resource.partition_keys == [expected_key]
        assert resource.partition_mode == "datetime"
