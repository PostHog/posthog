from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sumologic import (
    SumoLogicSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic import sumo_logic as sl
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.settings import SUMO_LOGIC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.source import SumoLogicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.sumo_logic import (
    SumoLogicResumeConfig,
    _message_row,
    _to_epoch_ms,
    base_url,
    validate_credentials,
)


def _response(json_data: Any = None, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=json_data)


def _driver() -> SourceDriver:
    return SourceDriver(SumoLogicSource(), SumoLogicSourceConfig(access_id="id", access_key="key", deployment="us1"))


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


class TestMessageRow:
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
            # 403 = genuine key missing the probed capability; must not block source creation.
            (403, True),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(_response({}, status=status_code))):
            is_valid, error = validate_credentials("us1", "id", "key")

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None


class TestCredentialRedaction:
    def test_connections_drop_webhook_secrets_but_keep_metadata(self) -> None:
        # A connection's destination URL carries the webhook auth token (Slack/PagerDuty put the
        # secret in the URL itself) and header fields can carry an Authorization credential; a
        # warehouse reader must never see them, only the connection's non-secret metadata.
        result = _driver().run(
            "connections",
            [
                _response(
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
            ],
        )

        assert result.items == [
            [{"id": "c1", "name": "prod-alerts", "type": "WebhookConnection", "description": "Slack alerts"}]
        ]

    def test_monitors_drop_nested_notification_payload_overrides(self) -> None:
        # A monitor's notification payload overrides live below the top level (under the
        # `notifications` list) and can carry destination credentials, so the shallow key filter
        # can't reach them; they must be stripped while the rest of the notification routing stays.
        result = _driver().run(
            "monitors",
            [
                _response(
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
            ],
        )

        assert result.items == [
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
        result = _driver().run(
            "users",
            [
                _response({"data": [{"id": "u1"}], "next": "tok-2"}),
                _response({"data": [{"id": "u2"}], "next": None}),
            ],
        )

        assert result.items == [[{"id": "u1"}], [{"id": "u2"}]]
        assert [s.token for s in result.saved_states] == ["tok-2"]
        assert result.params("token") == [None, "tok-2"]


class TestOffsetPagination:
    def test_advances_offset_and_terminates_on_short_page(self) -> None:
        page_size = SUMO_LOGIC_ENDPOINTS["monitors"].page_size

        result = _driver().run(
            "monitors",
            [
                _response([{"item": {"id": i}, "path": f"/m/{i}"} for i in range(page_size)]),
                _response([{"item": {"id": "last"}, "path": "/m/last"}]),
            ],
        )

        assert len(result.items) == 2
        assert result.items[0][0] == {"id": 0, "path": "/m/0"}
        assert result.items[1] == [{"id": "last", "path": "/m/last"}]
        assert [s.offset for s in result.saved_states] == [page_size]
        assert result.requests[1].param("offset") == str(page_size)
        assert result.requests[1].param("query") == "type:monitor"


class TestCollectorFanOut:
    def test_rows_carry_collector_id_and_drop_ingestion_url(self) -> None:
        # An HTTP source's `url` is itself a bearer credential for log ingestion, so it must be
        # redacted even though it arrives via the collector fan-out path; the parent collector id
        # is still stitched onto every row.
        result = _driver().run(
            "collector_sources",
            route(
                {
                    "/v1/collectors": [_response({"collectors": [{"id": 1}, {"id": 2}]})],
                    "/v1/collectors/1/sources": [
                        _response(
                            {
                                "sources": [
                                    {
                                        "id": 10,
                                        "name": "s10",
                                        "url": "https://collectors.sumologic.com/receiver/secret",
                                    }
                                ]
                            }
                        )
                    ],
                    "/v1/collectors/2/sources": [_response({"sources": [{"id": 10, "name": "other-s10"}]})],
                }
            ),
        )

        assert result.items == [
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

    def __call__(self, request: RecordedRequest) -> ScriptedResponse:
        method, path = request.method, request.path
        if method == "POST" and path.endswith("/v1/search/jobs"):
            self.created_jobs.append(request.json())
            return _response({"id": str(len(self.created_jobs))})
        if method == "DELETE":
            self.deleted_job_ids.append(path.rsplit("/", 1)[-1])
            return _response(None, status=204)
        if method == "GET" and path.endswith("/messages"):
            job_id = path.split("/")[-2]
            self.fetched_message_job_ids.append(job_id)
            offset = int(request.param("offset") or 0)
            count = self._count(job_id)
            messages = [
                {"map": {"_messageid": f"{job_id}-{i}", "_messagetime": "1767225600000"}} for i in range(offset, count)
            ]
            return _response({"messages": messages})
        if method == "GET":
            job_id = path.rsplit("/", 1)[-1]
            return _response({"state": "DONE GATHERING RESULTS", "messageCount": self._count(job_id)})
        raise UnexpectedRequest(f"unexpected request {method} {request.url}")


class TestLogSearchJobs:
    ONE_HOUR_MS = 3_600_000

    def test_resumes_from_saved_window_start(self) -> None:
        resume_start = int(datetime.now(UTC).timestamp() * 1000) - 10 * 60 * 1000
        api = FakeSearchJobApi(message_count_per_job=[1])

        _driver().run(
            "logs",
            api,
            resume_state=SumoLogicResumeConfig(log_window_start_ms=resume_start),
            incremental_field="message_time",
            db_incremental_field_last_value=0,
        )

        assert api.created_jobs[0]["from"] == resume_start

    def test_window_at_message_cap_is_split_without_fetching(self) -> None:
        # Job 1 (the full window) hits the cap; jobs 2 and 3 (the halves) fit.
        api = FakeSearchJobApi(message_count_per_job=[2, 1, 1])
        watermark = int(datetime.now(UTC).timestamp() * 1000) - 60 * 60 * 1000

        with mock.patch.object(sl, "SEARCH_JOB_MAX_MESSAGES", 2):
            result = _driver().run(
                "logs",
                api,
                incremental_field="message_time",
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
        assert len(result.rows) == 2

    def test_cancelled_job_raises(self) -> None:
        def handler(request: RecordedRequest) -> ScriptedResponse:
            if request.method == "POST":
                return _response({"id": "1"})
            return _response({"state": "CANCELLED"})

        result = _driver().run(
            "logs",
            handler,
            incremental_field="message_time",
            db_incremental_field_last_value=int(datetime.now(UTC).timestamp() * 1000) - 60_000,
        )

        assert isinstance(result.raised, ValueError)
        assert "cancelled" in str(result.raised)

    def test_watermark_in_future_yields_nothing(self) -> None:
        api = FakeSearchJobApi(message_count_per_job=[])

        result = _driver().run(
            "logs",
            api,
            incremental_field="message_time",
            db_incremental_field_last_value=int(datetime.now(UTC).timestamp() * 1000) + 60 * 60 * 1000,
        )

        assert result.rows == []
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
        response = _driver().run(endpoint, []).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.sort_mode == expected_sort_mode
        if expect_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["message_time"]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
