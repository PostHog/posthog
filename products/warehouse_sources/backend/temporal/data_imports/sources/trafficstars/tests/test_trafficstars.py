from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trafficstars import (
    TrafficStarsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trafficstars.source import TrafficStarsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trafficstars.trafficstars import (
    TrafficStarsResumeConfig,
    validate_credentials,
)

TOKEN = ScriptedResponse(json={"access_token": "tok", "expires_in": 36000, "token_type": "Bearer"})
INVALID_GRANT = ScriptedResponse(
    status=400,
    json={
        "status": 400,
        "error": "EXTERNAL_SERVICE_ERROR",
        "message": "Unsuccessful interaction with Keycloak: {'error': 'invalid_grant', 'error_description': 'Invalid refresh token'}",
    },
)


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[None]:
    with time_machine.travel(datetime(2026, 10, 15, 12, tzinfo=UTC), tick=False):
        yield


def _run(endpoint: str, api_path: str, responses: list[ScriptedResponse], **inputs: Any) -> DriveResult:
    script = route({"/v1/auth/token": [TOKEN], api_path: responses})
    return SourceDriver(TrafficStarsSource(), TrafficStarsSourceConfig(api_key="ts_key")).run(
        endpoint, script, **inputs
    )


def _api(result: DriveResult) -> list[RecordedRequest]:
    return [request for request in result.requests if request.path != "/v1/auth/token"]


class TestLists:
    def test_campaigns_exchange_the_key_once_and_read_one_page(self) -> None:
        result = _run("campaigns", "/v1.1/campaigns", [ScriptedResponse(json={"response": [{"id": 1}, {"id": 2}]})])

        assert result.raised is None
        token_request = result.requests[0]
        assert token_request.path == "/v1/auth/token"
        assert token_request.body == b"grant_type=refresh_token&refresh_token=ts_key"
        assert [r.headers["authorization"] for r in _api(result)] == ["Bearer tok"]
        assert [row["id"] for row in result.rows] == [1, 2]

    def test_creatives_walk_pages_until_page_count(self) -> None:
        result = _run(
            "creatives",
            "/v2/banners",
            [
                ScriptedResponse(json={"page": 1, "page_count": 2, "response": [{"id": 10}]}),
                ScriptedResponse(json={"page": 2, "page_count": 2, "response": [{"id": 11}]}),
            ],
        )

        assert result.raised is None
        assert [(r.param("page"), r.param("size")) for r in _api(result)] == [("1", "100"), ("2", "100")]
        assert [row["id"] for row in result.rows] == [10, 11]
        assert result.saved_states == [TrafficStarsResumeConfig(next_page=2)]


class TestDailyStatistics:
    def test_requests_one_inclusive_day_at_a_time_from_the_watermark(self) -> None:
        result = _run(
            "campaign_statistics_daily",
            "/v2/campaigns/statistics",
            [
                ScriptedResponse(json={"data": [{"id": 123, "name": "Campaign", "impressions": 6627, "costs": 0.33}]}),
                ScriptedResponse(json={"data": []}),
                ScriptedResponse(json={"data": [{"id": 123, "name": "Campaign", "impressions": 10, "costs": 0.01}]}),
            ],
            incremental_field="date",
            db_incremental_field_last_value=date(2026, 10, 13),
        )

        assert result.raised is None
        api = _api(result)
        assert [r.method for r in api] == ["POST"] * 3
        assert [(r.json()["date_from"], r.json()["date_to"]) for r in api] == [
            ("2026-10-13", "2026-10-13"),
            ("2026-10-14", "2026-10-14"),
            ("2026-10-15", "2026-10-15"),
        ]
        assert api[0].json()["group_by"] == "campaign"
        assert [(row["date"], row["id"], row["impressions"]) for row in result.rows] == [
            (date(2026, 10, 13), 123, 6627),
            (date(2026, 10, 15), 123, 10),
        ]
        assert result.saved_states == [
            TrafficStarsResumeConfig(next_day="2026-10-14"),
            TrafficStarsResumeConfig(next_day="2026-10-15"),
        ]
        assert TrafficStarsResumeConfig(next_day="2026-10-15") in result.committed_states

    @pytest.mark.parametrize(
        ("inputs", "resume_state", "expected_first_day"),
        [
            ({}, None, "2026-04-18"),
            ({"history_start": datetime(2026, 4, 1, tzinfo=UTC)}, None, "2026-04-01"),
            (
                {
                    "incremental_field": "date",
                    "db_incremental_field_last_value": date(2026, 4, 1),
                    "history_start": datetime(2026, 5, 1, tzinfo=UTC),
                },
                None,
                "2026-04-01",
            ),
            ({}, TrafficStarsResumeConfig(next_day="2026-10-15"), "2026-10-15"),
        ],
    )
    def test_starts_at_the_saved_day_the_watermark_or_the_recorded_history_start(
        self, inputs: dict[str, Any], resume_state: TrafficStarsResumeConfig | None, expected_first_day: str
    ) -> None:
        config = TrafficStarsSourceConfig(api_key="ts_key")
        script = route(
            {"/v1/auth/token": [TOKEN], "/v2/campaigns/statistics": [ScriptedResponse(json={"data": []})] * 250}
        )
        result = SourceDriver(TrafficStarsSource(), config).run(
            "campaign_statistics_daily", script, resume_state=resume_state, **inputs
        )

        assert result.raised is None
        assert _api(result)[0].json()["date_from"] == expected_first_day


class TestErrors:
    def test_a_rejected_key_fails_with_the_permanent_marker(self) -> None:
        result = SourceDriver(TrafficStarsSource(), TrafficStarsSourceConfig(api_key="bad")).run(
            "campaigns", always(INVALID_GRANT)
        )

        assert result.raised is not None
        assert OAUTH2_PERMANENT_ERROR_MARKER in str(result.raised)

    @pytest.mark.parametrize(
        ("token_response", "creatives_response", "expected_valid", "message_fragment"),
        [
            (TOKEN, ScriptedResponse(json={"page": 1, "page_count": 1, "response": []}), True, None),
            (TOKEN, ScriptedResponse(status=403, json={}), False, "advertiser account"),
            (TOKEN, ScriptedResponse(status=503, json={}), False, "Could not connect"),
            (INVALID_GRANT, None, False, "rejected the API key"),
            (ScriptedResponse(status=500, json={}), None, False, "Could not connect"),
            (ConnectionError("boom"), None, False, "Could not connect"),
        ],
    )
    def test_the_credential_probe_maps_the_token_exchange_and_the_data_read(
        self,
        token_response: Any,
        creatives_response: ScriptedResponse | None,
        expected_valid: bool,
        message_fragment: str | None,
    ) -> None:
        with scripted_network([token_response, *([creatives_response] if creatives_response else [])]) as network:
            is_valid, message = validate_credentials("ts_key")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message
        # Setup waits on the probe, so a failed request gets no retry.
        assert len(network.requests_log) == (2 if creatives_response is not None else 1)
        if creatives_response is not None:
            assert network.requests_log[-1].headers["authorization"] == "Bearer tok"
