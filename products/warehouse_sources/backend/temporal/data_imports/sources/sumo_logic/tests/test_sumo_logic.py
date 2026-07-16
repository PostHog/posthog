from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic import sumo_logic as sl
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.settings import SUMO_LOGIC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.sumo_logic import (
    SumoLogicResumeConfig,
    _extract_items,
    _message_row,
    _to_epoch_ms,
    _unnest_item,
    base_url,
    sumo_logic_source,
    validate_credentials,
)


def _response(json_data: Any = None, status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.content = b"{}" if json_data is not None else b""
    resp.json.return_value = json_data
    return resp


def _make_manager(resume_state: SumoLogicResumeConfig | None = None) -> tuple[mock.MagicMock, list[Any]]:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    saved: list[Any] = []
    manager.save_state.side_effect = lambda state: saved.append(state)
    return manager, saved


def _run_get_rows(
    endpoint: str,
    request_handler: Any,
    manager: mock.MagicMock,
    search_query: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[list[dict[str, Any]]]:
    with mock.patch.object(sl, "make_tracked_session") as mock_session:
        mock_session.return_value.request.side_effect = request_handler
        return list(
            sl.get_rows(
                deployment="us1",
                access_id="id",
                access_key="key",
                endpoint=endpoint,
                search_query=search_query,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
        )


class TestBaseUrl:
    @pytest.mark.parametrize(
        ("deployment", "expected"),
        [
            ("us1", "https://api.sumologic.com/api"),
            ("eu", "https://api.eu.sumologic.com/api"),
            ("jp", "https://api.jp.sumologic.com/api"),
            # Unknown / spoofed deployments fall back to the default US1 host.
            ("evil.example.com", "https://api.sumologic.com/api"),
            (None, "https://api.sumologic.com/api"),
        ],
    )
    def test_base_url(self, deployment: Any, expected: str) -> None:
        assert base_url(deployment) == expected


class TestToEpochMs:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 1, 1, tzinfo=UTC), 1767225600000),
            (datetime(2026, 1, 1), 1767225600000),  # naive treated as UTC
            (date(2026, 1, 1), 1767225600000),
            (1767225600000, 1767225600000),
            ("2026-01-01T00:00:00", 1767225600000),
        ],
    )
    def test_to_epoch_ms(self, value: Any, expected: int) -> None:
        assert _to_epoch_ms(value) == expected


class TestExtractAndUnnest:
    def test_wrapped_data_key(self) -> None:
        config = SUMO_LOGIC_ENDPOINTS["users"]
        assert _extract_items({"data": [{"id": "u1"}]}, config) == [{"id": "u1"}]

    def test_missing_data_key_returns_empty(self) -> None:
        config = SUMO_LOGIC_ENDPOINTS["users"]
        assert _extract_items({"next": None}, config) == []

    def test_top_level_list(self) -> None:
        config = SUMO_LOGIC_ENDPOINTS["monitors"]  # data_key=None
        assert _extract_items([{"item": {"id": 1}}], config) == [{"item": {"id": 1}}]

    def test_unnest_lifts_item_and_keeps_siblings(self) -> None:
        config = SUMO_LOGIC_ENDPOINTS["monitors"]  # nest_key="item"
        row = _unnest_item({"item": {"id": 1, "name": "mon"}, "path": "/Monitors/mon"}, config)
        assert row == {"id": 1, "name": "mon", "path": "/Monitors/mon"}

    def test_unnest_noop_without_nest_key(self) -> None:
        config = SUMO_LOGIC_ENDPOINTS["users"]
        assert _unnest_item({"id": "u1"}, config) == {"id": "u1"}


class TestMessageRow:
    def test_derives_message_time_from_epoch_millis(self) -> None:
        row = _message_row({"map": {"_messageid": "-9", "_messagetime": "1767225600000", "_raw": "boom"}})
        assert row["message_time"] == datetime(2026, 1, 1, tzinfo=UTC)
        assert row["_raw"] == "boom"

    @pytest.mark.parametrize("raw_time", [None, "not-a-number"])
    def test_unparseable_message_time_is_none(self, raw_time: Any) -> None:
        message = {"map": {"_messageid": "-9"}}
        if raw_time is not None:
            message["map"]["_messagetime"] = raw_time
        assert _message_row(message)["message_time"] is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            # 403 = genuine key missing the probed capability; must not block source creation.
            (403, True),
            (401, False),
            (500, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.sumo_logic.make_tracked_session"
    )
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected_valid: bool) -> None:
        mock_session.return_value.get.return_value = _response(status=status_code)

        is_valid, error = validate_credentials("us1", "id", "key")

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.sumo_logic.make_tracked_session"
    )
    def test_request_exception_is_caught(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        is_valid, error = validate_credentials("us1", "id", "key")
        assert is_valid is False
        assert error is not None


class TestSessionPrivacy:
    def test_session_excludes_bodies_from_sample_capture(self) -> None:
        # Raw `_raw` log bodies are free-form customer data; re-enabling sample capture would copy
        # them into HTTP sample storage where the name-based scrubbers can't redact embedded secrets.
        manager, _saved = _make_manager()
        with mock.patch.object(sl, "make_tracked_session") as mock_session_factory:
            mock_session_factory.return_value.request.return_value = _response({"data": [], "next": None})
            list(
                sl.get_rows(
                    deployment="us1",
                    access_id="id",
                    access_key="key",
                    endpoint="users",
                    search_query=None,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        assert mock_session_factory.call_args.kwargs["capture"] is False
        assert "key" in mock_session_factory.call_args.kwargs["redact_values"]


class TestCredentialRedaction:
    def test_connections_drop_webhook_secrets_but_keep_metadata(self) -> None:
        # A connection's destination URL carries the webhook auth token (Slack/PagerDuty put the
        # secret in the URL itself) and header fields can carry an Authorization credential; a
        # warehouse reader must never see them, only the connection's non-secret metadata.
        manager, _saved = _make_manager()

        def handler(method: str, url: str, json: Any = None, timeout: Any = None) -> Any:
            return _response(
                {
                    "data": [
                        {
                            "id": "c1",
                            "name": "prod-alerts",
                            "type": "WebhookConnection",
                            "description": "Slack alerts",
                            "url": "https://hooks.slack.com/services/T00/B00/secret-token",
                            "headers": [{"name": "Authorization", "value": "Bearer secret"}],
                            "customHeaders": {"X-Api-Key": "secret"},
                            "defaultPayload": "{...}",
                        }
                    ],
                    "next": None,
                }
            )

        rows = _run_get_rows("connections", handler, manager)

        assert rows == [
            [{"id": "c1", "name": "prod-alerts", "type": "WebhookConnection", "description": "Slack alerts"}]
        ]

    def test_monitors_drop_nested_notification_payload_overrides(self) -> None:
        # A monitor's notification payload overrides live below the top level (under the
        # `notifications` list) and can carry destination credentials, so the shallow key filter
        # can't reach them; they must be stripped while the rest of the notification routing stays.
        manager, _saved = _make_manager()

        def handler(method: str, url: str, json: Any = None, timeout: Any = None) -> Any:
            return _response(
                [
                    {
                        "item": {
                            "id": "m1",
                            "name": "high-errors",
                            "notifications": [
                                {
                                    "notification": {
                                        "connectionType": "Webhook",
                                        "connectionId": "conn-1",
                                        "payloadOverride": '{"token": "secret"}',
                                        "resolutionPayloadOverride": '{"token": "secret"}',
                                    },
                                    "runForTriggerTypes": ["Critical"],
                                }
                            ],
                        },
                        "path": "/m/m1",
                    }
                ]
            )

        rows = _run_get_rows("monitors", handler, manager)

        assert rows == [
            [
                {
                    "id": "m1",
                    "name": "high-errors",
                    "notifications": [
                        {
                            "notification": {"connectionType": "Webhook", "connectionId": "conn-1"},
                            "runForTriggerTypes": ["Critical"],
                        }
                    ],
                    "path": "/m/m1",
                }
            ]
        ]


class TestTokenPagination:
    def test_yields_pages_saves_token_after_yield_and_sends_it(self) -> None:
        manager, saved = _make_manager()
        requested: list[str] = []

        def handler(method: str, url: str, json: Any = None, timeout: Any = None) -> Any:
            requested.append(url)
            if len(requested) == 1:
                return _response({"data": [{"id": "u1"}], "next": "tok-2"})
            return _response({"data": [{"id": "u2"}], "next": None})

        rows = _run_get_rows("users", handler, manager)

        assert rows == [[{"id": "u1"}], [{"id": "u2"}]]
        assert [s.token for s in saved] == ["tok-2"]
        second_query = parse_qs(urlparse(requested[1]).query)
        assert second_query["token"] == ["tok-2"]

    def test_resumes_from_saved_token(self) -> None:
        manager, _saved = _make_manager(SumoLogicResumeConfig(token="tok-resume"))
        requested: list[str] = []

        def handler(method: str, url: str, json: Any = None, timeout: Any = None) -> Any:
            requested.append(url)
            return _response({"data": [{"id": "u9"}], "next": None})

        _run_get_rows("users", handler, manager)

        first_query = parse_qs(urlparse(requested[0]).query)
        assert first_query["token"] == ["tok-resume"]


class TestOffsetPagination:
    def test_advances_offset_and_terminates_on_short_page(self) -> None:
        manager, saved = _make_manager()
        page_size = SUMO_LOGIC_ENDPOINTS["monitors"].page_size
        requested: list[str] = []

        def handler(method: str, url: str, json: Any = None, timeout: Any = None) -> Any:
            requested.append(url)
            if len(requested) == 1:
                return _response([{"item": {"id": i}, "path": f"/m/{i}"} for i in range(page_size)])
            return _response([{"item": {"id": "last"}, "path": "/m/last"}])

        rows = _run_get_rows("monitors", handler, manager)

        assert len(rows) == 2
        assert rows[0][0] == {"id": 0, "path": "/m/0"}
        assert rows[1] == [{"id": "last", "path": "/m/last"}]
        assert [s.offset for s in saved] == [page_size]
        second_query = parse_qs(urlparse(requested[1]).query)
        assert second_query["offset"] == [str(page_size)]
        assert second_query["query"] == ["type:monitor"]


class TestCollectorFanOut:
    def test_rows_carry_collector_id_and_drop_ingestion_url(self) -> None:
        # An HTTP source's `url` is itself a bearer credential for log ingestion, so it must be
        # redacted even though it arrives via the collector fan-out path; the parent collector id
        # is still stitched onto every row.
        manager, _saved = _make_manager()
        requested: list[str] = []

        def handler(method: str, url: str, json: Any = None, timeout: Any = None) -> Any:
            requested.append(url)
            path = urlparse(url).path
            if path.endswith("/v1/collectors"):
                return _response({"collectors": [{"id": 1}, {"id": 2}]})
            if path.endswith("/v1/collectors/1/sources"):
                return _response(
                    {"sources": [{"id": 10, "name": "s10", "url": "https://collectors.sumologic.com/receiver/secret"}]}
                )
            if path.endswith("/v1/collectors/2/sources"):
                return _response({"sources": [{"id": 10, "name": "other-s10"}]})
            raise AssertionError(f"unexpected URL {url}")

        rows = _run_get_rows("collector_sources", handler, manager)

        assert rows == [
            [
                {"id": 10, "name": "s10", "collector_id": 1},
                {"id": 10, "name": "other-s10", "collector_id": 2},
            ]
        ]


class FakeSearchJobApi:
    """Fakes the submit/poll/fetch/delete Search Job flow, recording created jobs and deletions."""

    def __init__(self, message_count_per_job: list[int]) -> None:
        self.message_count_per_job = message_count_per_job
        self.created_jobs: list[dict[str, Any]] = []
        self.deleted_job_ids: list[str] = []
        self.fetched_message_job_ids: list[str] = []

    def _count(self, job_id: str) -> int:
        return self.message_count_per_job[int(job_id) - 1]

    def __call__(self, method: str, url: str, json: Any = None, timeout: Any = None) -> Any:
        parsed = urlparse(url)
        if method == "POST" and parsed.path.endswith("/v1/search/jobs"):
            self.created_jobs.append(json)
            return _response({"id": str(len(self.created_jobs))})
        if method == "DELETE":
            self.deleted_job_ids.append(parsed.path.rsplit("/", 1)[-1])
            return _response(None, status=204)
        if method == "GET" and parsed.path.endswith("/messages"):
            job_id = parsed.path.split("/")[-2]
            self.fetched_message_job_ids.append(job_id)
            query = parse_qs(parsed.query)
            offset = int(query["offset"][0])
            count = self._count(job_id)
            messages = [
                {"map": {"_messageid": f"{job_id}-{i}", "_messagetime": "1767225600000"}} for i in range(offset, count)
            ]
            return _response({"messages": messages})
        if method == "GET":
            job_id = parsed.path.rsplit("/", 1)[-1]
            return _response({"state": "DONE GATHERING RESULTS", "messageCount": self._count(job_id)})
        raise AssertionError(f"unexpected request {method} {url}")


class TestLogSearchJobs:
    ONE_HOUR_MS = 3_600_000

    def test_windows_start_at_watermark_and_are_contiguous(self) -> None:
        manager, saved = _make_manager()
        api = FakeSearchJobApi(message_count_per_job=[1, 1])
        watermark = datetime.now(UTC).timestamp() * 1000 - 90 * 60 * 1000  # 90 minutes ago

        with mock.patch.object(sl, "SEARCH_JOB_INITIAL_WINDOW", timedelta(hours=1)):
            rows = _run_get_rows(
                "logs",
                api,
                manager,
                search_query="_sourceCategory=prod",
                should_use_incremental_field=True,
                db_incremental_field_last_value=int(watermark),
            )

        assert len(api.created_jobs) == 2
        first, second = api.created_jobs
        assert first["query"] == "_sourceCategory=prod"
        assert first["from"] == int(watermark)
        assert first["to"] == int(watermark) + self.ONE_HOUR_MS
        assert second["from"] == first["to"]
        assert second["to"] > second["from"]
        # Rows carry the derived message_time; both jobs' pages were yielded and both jobs deleted.
        assert [row["message_time"] for page in rows for row in page] == [datetime(2026, 1, 1, tzinfo=UTC)] * 2
        assert api.deleted_job_ids == ["1", "2"]
        # State saved once — after the first window's rows, never after the final window.
        assert [s.log_window_start_ms for s in saved] == [first["to"]]

    def test_resumes_from_saved_window_start(self) -> None:
        resume_start = int(datetime.now(UTC).timestamp() * 1000) - 10 * 60 * 1000
        manager, _saved = _make_manager(SumoLogicResumeConfig(log_window_start_ms=resume_start))
        api = FakeSearchJobApi(message_count_per_job=[1])

        _run_get_rows("logs", api, manager, should_use_incremental_field=True, db_incremental_field_last_value=0)

        assert api.created_jobs[0]["from"] == resume_start

    def test_blank_search_query_defaults_to_wildcard(self) -> None:
        manager, _saved = _make_manager()
        api = FakeSearchJobApi(message_count_per_job=[0])
        watermark = int(datetime.now(UTC).timestamp() * 1000) - 60_000

        _run_get_rows(
            "logs",
            api,
            manager,
            search_query="  ",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert api.created_jobs[0]["query"] == "*"

    def test_window_at_message_cap_is_split_without_fetching(self) -> None:
        manager, _saved = _make_manager()
        # Job 1 (the full window) hits the cap; jobs 2 and 3 (the halves) fit.
        api = FakeSearchJobApi(message_count_per_job=[2, 1, 1])
        watermark = int(datetime.now(UTC).timestamp() * 1000) - 60 * 60 * 1000

        with mock.patch.object(sl, "SEARCH_JOB_MAX_MESSAGES", 2):
            rows = _run_get_rows(
                "logs",
                api,
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )

        assert len(api.created_jobs) == 3
        first, first_half, second_half = api.created_jobs
        assert first_half["from"] == first["from"]
        assert first_half["to"] == second_half["from"]
        assert second_half["to"] == first["to"]
        # The capped job was deleted without its messages being fetched.
        assert "1" not in api.fetched_message_job_ids
        assert api.deleted_job_ids[0] == "1"
        assert len([row for page in rows for row in page]) == 2

    def test_cancelled_job_raises(self) -> None:
        manager, _saved = _make_manager()

        def handler(method: str, url: str, json: Any = None, timeout: Any = None) -> Any:
            if method == "POST":
                return _response({"id": "1"})
            return _response({"state": "CANCELLED"})

        with pytest.raises(ValueError, match="cancelled"):
            _run_get_rows(
                "logs",
                handler,
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=int(datetime.now(UTC).timestamp() * 1000) - 60_000,
            )

    def test_watermark_in_future_yields_nothing(self) -> None:
        manager, _saved = _make_manager()
        api = FakeSearchJobApi(message_count_per_job=[])

        rows = _run_get_rows(
            "logs",
            api,
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=int(datetime.now(UTC).timestamp() * 1000) + 60 * 60 * 1000,
        )

        assert rows == []
        assert api.created_jobs == []


class TestSumoLogicSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expected_pks", "expected_sort_mode", "expect_partition"),
        [
            ("logs", ["_messageid", "_messagetime"], "desc", True),
            ("users", ["id"], "asc", False),
            ("collector_sources", ["collector_id", "id"], "asc", False),
            ("health_events", ["eventId"], "asc", False),
        ],
    )
    def test_source_response_shape(
        self, endpoint: str, expected_pks: list[str], expected_sort_mode: str, expect_partition: bool
    ) -> None:
        response = sumo_logic_source(
            deployment="us1",
            access_id="id",
            access_key="key",
            endpoint=endpoint,
            search_query=None,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.sort_mode == expected_sort_mode
        if expect_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["message_time"]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
