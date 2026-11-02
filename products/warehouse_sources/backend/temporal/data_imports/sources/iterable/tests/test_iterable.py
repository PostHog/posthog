from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.iterable import (
    IterableSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.iterable import (
    IterableResumeConfig,
    _parse_iterable_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.source import IterableSource


def _driver() -> SourceDriver:
    return SourceDriver(IterableSource(), IterableSourceConfig(api_key="key", region="us"))


class TestValidateCredentials:
    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("key", "us") is False

        assert network.requests_log
        assert {request.path for request in network.requests_log} == {"/api/channels"}


class TestPagination:
    def test_follows_next_page_url_and_saves_state_after_yield(self) -> None:
        result = _driver().run(
            "campaigns",
            [
                ScriptedResponse(json={"campaigns": [{"id": 1}], "nextPageUrl": "/api/campaigns?page=2"}),
                ScriptedResponse(json={"campaigns": [{"id": 2}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}]
        # Second request follows the resolved (relative -> absolute) next URL.
        assert result.urls == [
            "https://api.iterable.com/api/campaigns",
            "https://api.iterable.com/api/campaigns?page=2",
        ]
        # State is saved once — after the first page yields, pointing at the resolved next URL.
        assert result.saved_states == [IterableResumeConfig(next_url="https://api.iterable.com/api/campaigns?page=2")]

    def test_resumes_from_saved_state(self) -> None:
        result = _driver().run(
            "campaigns",
            [ScriptedResponse(json={"campaigns": [{"id": 9}]})],
            resume_state=IterableResumeConfig(next_url="https://api.iterable.com/api/campaigns?page=5"),
        )

        assert result.raised is None
        assert result.urls[0] == "https://api.iterable.com/api/campaigns?page=5"

    def test_off_host_resume_state_restarts_from_top(self) -> None:
        # A resume URL pointing at another host (corrupted/poisoned state) must not be requested
        # with the Api-Key header — pagination restarts from the endpoint's base URL instead.
        result = _driver().run(
            "campaigns",
            [ScriptedResponse(json={"campaigns": [{"id": 9}]})],
            resume_state=IterableResumeConfig(next_url="https://evil.com/api/campaigns?page=5"),
        )

        assert result.raised is None
        assert result.urls[0] == "https://api.iterable.com/api/campaigns"

    def test_off_host_next_page_url_stops_pagination(self) -> None:
        # An off-host absolute `nextPageUrl` (attacker-echoed) is not followed — pagination stops
        # cleanly after the first page rather than sending the Api-Key header off-host.
        result = _driver().run(
            "campaigns",
            [ScriptedResponse(json={"campaigns": [{"id": 1}], "nextPageUrl": "https://evil.com/api/campaigns?page=2"})],
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert result.paths == ["/api/campaigns"]
        assert result.saved_states == []


class TestParseIterableDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2024-01-31 18:04:05 +00:00", datetime(2024, 1, 31, 18, 4, 5, tzinfo=UTC)),
            ("2024-01-31 18:04:05.250 +00:00", datetime(2024, 1, 31, 18, 4, 5, 250000, tzinfo=UTC)),
            ("2024-01-31 20:04:05 +02:00", datetime(2024, 1, 31, 18, 4, 5, tzinfo=UTC)),
            ("2024-01-31 18:04:05", datetime(2024, 1, 31, 18, 4, 5, tzinfo=UTC)),
            ("not a date", "not a date"),
            (1706724245000, 1706724245000),
            (None, None),
        ],
    )
    def test_parse(self, value: Any, expected: Any) -> None:
        assert _parse_iterable_datetime(value) == expected


class TestExport:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel(datetime(2024, 3, 1, tzinfo=UTC), tick=False):
            yield

    def test_parses_cursor_field_into_datetime(self) -> None:
        result = _driver().run(
            "users",
            [ScriptedResponse(body=b'{"email":"a@example.com","profileUpdatedAt":"2024-02-20 10:00:00 +00:00"}\n')],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 2, 10, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.rows == [{"email": "a@example.com", "profileUpdatedAt": datetime(2024, 2, 20, 10, tzinfo=UTC)}]

    @pytest.mark.parametrize(
        "last_value, resume_state, expected_start",
        [
            (None, None, "2023-03-02 00:00:00 +00:00"),
            ("2024-02-20 12:00:00 +00:00", None, "2024-02-20 12:00:00 +00:00"),
            (
                datetime(2024, 2, 20, tzinfo=UTC),
                IterableResumeConfig(export_window_start="2024-02-10T00:00:00+00:00"),
                "2024-02-10 00:00:00 +00:00",
            ),
        ],
    )
    def test_first_window_start(self, last_value: Any, resume_state: Any, expected_start: str) -> None:
        result = _driver().run(
            "purchase",
            always(ScriptedResponse(body=b"")),
            resume_state=resume_state,
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.rows == []
        assert result.requests[0].param("startDateTime") == expected_start


class TestFanOut:
    def test_list_users_carries_list_id_and_skips_blank_lines(self) -> None:
        result = _driver().run(
            "list_users",
            [
                ScriptedResponse(json={"lists": [{"id": 11}, {"id": 12}]}),
                ScriptedResponse(body=b"a@example.com\n\nb@example.com\n"),
                ScriptedResponse(body=b"a@example.com\n"),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"listId": 11, "email": "a@example.com"},
            {"listId": 11, "email": "b@example.com"},
            {"listId": 12, "email": "a@example.com"},
        ]
        assert result.params("listId")[1:] == ["11", "12"]

    def test_campaign_metrics_batches_campaign_ids_and_parses_csv(self) -> None:
        result = _driver().run(
            "campaign_metrics",
            [
                ScriptedResponse(json={"campaigns": [{"id": i} for i in range(1, 102)]}),
                ScriptedResponse(body=b"id,Total Email Sends,Unique Email Opens\n1,100,40\n2,50,\n"),
                ScriptedResponse(body=b"id,Total Email Sends,Unique Email Opens\n101,7,3\n"),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": 1, "Total Email Sends": "100", "Unique Email Opens": "40"},
            {"id": 2, "Total Email Sends": "50", "Unique Email Opens": None},
            {"id": 101, "Total Email Sends": "7", "Unique Email Opens": "3"},
        ]
        assert [request.query["campaignId"] for request in result.requests[1:]] == [
            tuple(str(i) for i in range(1, 101)),
            ("101",),
        ]
