import re
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import responses
from requests import HTTPError, PreparedRequest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.proofpointtap import (
    ProofpointTapSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.proofpoint_tap.proofpoint_tap import (
    TapCursor,
    TapResumeState,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.proofpoint_tap.source import ProofpointTapSource

NOW = datetime(2026, 1, 8, 12, tzinfo=UTC)
ROOT = "https://tap-api-v2.proofpoint.com/v2"
BASE = f"{ROOT}/siem"
CONFIG = ProofpointTapSourceConfig.from_dict({"service_principal": "example-principal", "secret": "example-secret"})


class Harness:
    def __init__(
        self,
        endpoint: str = "clicks_blocked",
        incremental: bool = True,
        watermark: str | datetime | None = NOW - timedelta(hours=2),
        stored: TapCursor | None = None,
        resume: TapResumeState | None = None,
    ) -> None:
        self.source = ProofpointTapSource()
        self.cursor = SourceCursorManager(TapCursor, stored, self.source)
        self.manager = MagicMock(spec=ResumableSourceManager)
        self.manager.can_resume.return_value = resume is not None
        self.manager.load_state.return_value = resume
        self.inputs = SourceInputs(
            schema_name=endpoint,
            schema_id="schema-test",
            source_id="source-test",
            team_id=1,
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
            db_incremental_field_earliest_value=None,
            incremental_field="query_end_time",
            incremental_field_type=None,
            job_id="job-test",
            logger=MagicMock(),
            reset_pipeline=False,
            source_cursor=self.cursor,
        )
        self.response = self.source.source_for_pipeline(CONFIG, self.manager, self.inputs)

    def rows(self) -> list[dict[str, Any]]:
        return [row for batch in cast(Iterable[list[dict[str, Any]]], self.response.items()) for row in batch]


def query(request: PreparedRequest) -> dict[str, list[str]]:
    return parse_qs(urlparse(request.url or "").query)


def add_windows(path: str, selector: str, rows: list[dict[str, Any]]) -> None:
    def callback(request: PreparedRequest) -> tuple[int, dict[str, str], str]:
        end = query(request)["interval"][0].split("/")[1]
        return 200, {"Content-Type": "application/json"}, json.dumps({"queryEndTime": end, selector: rows})

    responses.add_callback(responses.GET, f"{BASE}/{path}", callback=callback)


@pytest.mark.parametrize(
    ("endpoint", "path", "selector", "key", "event_time"),
    [
        ("clicks_blocked", "clicks/blocked", "clicksBlocked", "id", "clickTime"),
        ("clicks_permitted", "clicks/permitted", "clicksPermitted", "id", "clickTime"),
        ("messages_blocked", "messages/blocked", "messagesBlocked", "GUID", "messageTime"),
        ("messages_delivered", "messages/delivered", "messagesDelivered", "GUID", "messageTime"),
    ],
)
@time_machine.travel(NOW, tick=False)
@responses.activate
def test_windows_auth_and_late_events(endpoint: str, path: str, selector: str, key: str, event_time: str) -> None:
    old_event = "2025-12-20T05:00:00Z"
    add_windows(path, selector, [{key: "event-a", event_time: old_event, "recipient": "user@example.com"}])
    harness = Harness(endpoint=endpoint)
    rows = harness.rows()

    assert len(responses.calls) == 2
    assert [query(call.request)["interval"][0] for call in responses.calls] == [
        "2026-01-08T09:59:00+00:00/2026-01-08T10:59:00+00:00",
        "2026-01-08T10:59:00+00:00/2026-01-08T11:59:00+00:00",
    ]
    assert all(query(call.request)["format"] == ["json"] for call in responses.calls)
    assert responses.calls[0].request.headers["Authorization"] == ("Basic ZXhhbXBsZS1wcmluY2lwYWw6ZXhhbXBsZS1zZWNyZXQ=")
    assert rows[0][event_time] == old_event
    assert rows[-1]["query_end_time"] == NOW - timedelta(minutes=1)
    assert harness.response.primary_keys == [key]
    assert harness.response.partition_keys == [event_time]
    assert harness.response.sort_mode == "desc"
    assert harness.cursor.staged == TapCursor(query_end_time="2026-01-08T11:59:00+00:00")
    assert harness.manager.save_state.call_count == 2
    assert harness.manager.safe_point.call_count == 2
    harness.manager.clear_state.assert_not_called()
    assert harness.response.on_complete is not None
    harness.response.on_complete()
    harness.manager.clear_state.assert_called_once()


@pytest.mark.parametrize("watermark", ["2025-01-01T00:00:00Z", datetime(2025, 1, 1), datetime(2025, 1, 1, tzinfo=UTC)])
@time_machine.travel(NOW, tick=False)
@responses.activate
def test_expired_watermark_is_clamped_to_retention(watermark: str | datetime) -> None:
    add_windows("clicks/blocked", "clicksBlocked", [])
    harness = Harness(watermark=watermark)
    harness.rows()
    assert query(responses.calls[0].request)["interval"][0].startswith("2026-01-01T12:02:00+00:00/")
    assert len(responses.calls) == 168


@time_machine.travel(NOW, tick=False)
@responses.activate
def test_empty_windows_advance_durable_cursor_and_take_priority_over_row_watermark() -> None:
    add_windows("clicks/blocked", "clicksBlocked", [])
    harness = Harness(stored=TapCursor(query_end_time="2026-01-08T11:00:00Z"), watermark="2025-12-20T00:00:00Z")
    assert harness.rows() == []
    assert len(responses.calls) == 1
    assert query(responses.calls[0].request)["interval"] == ["2026-01-08T10:59:00+00:00/2026-01-08T11:59:00+00:00"]
    assert harness.cursor.staged == TapCursor(query_end_time="2026-01-08T11:59:00+00:00")


@pytest.mark.parametrize("next_start", ["2026-01-08T11:00:00Z", "2026-01-08T11:30:00Z"])
@time_machine.travel(NOW, tick=False)
@responses.activate
def test_resume_keeps_original_upper_bound_and_completed_cursor(next_start: str) -> None:
    add_windows("clicks/blocked", "clicksBlocked", [])
    harness = Harness(resume=TapResumeState(next_start=next_start, end="2026-01-08T11:30:00Z"))
    assert harness.rows() == []
    assert len(responses.calls) == (1 if "11:00" in next_start else 0)
    if responses.calls:
        assert query(responses.calls[0].request)["interval"] == ["2026-01-08T11:00:00+00:00/2026-01-08T11:30:00+00:00"]
    assert harness.cursor.staged == TapCursor(query_end_time="2026-01-08T11:30:00+00:00")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"queryEndTime": "2026-01-08T10:59:00Z"},
        {"queryEndTime": None, "clicksBlocked": []},
        {"queryEndTime": "invalid-time", "clicksBlocked": []},
        {"queryEndTime": "2026-01-08T10:59:00Z", "clicksBlocked": {}},
        {"queryEndTime": "2026-01-08T10:59:00Z", "clicksBlocked": ["bad"]},
        {"queryEndTime": "2026-01-08T10:59:00Z", "clicksBlocked": [{}]},
        {"queryEndTime": "2026-01-08T09:59:00Z", "clicksBlocked": []},
        {"queryEndTime": "2026-01-08T10:30:00Z", "clicksBlocked": []},
        {"queryEndTime": "2026-01-08T12:00:00Z", "clicksBlocked": []},
    ],
)
@time_machine.travel(NOW, tick=False)
@responses.activate
def test_bad_response_never_advances_state(payload: dict[str, Any]) -> None:
    responses.get(f"{BASE}/clicks/blocked", json=payload)
    harness = Harness()
    with pytest.raises(ValueError):
        harness.rows()
    harness.manager.save_state.assert_not_called()
    assert harness.cursor.staged is None


@pytest.mark.parametrize("status", [401, 403, 429, 500])
@time_machine.travel(NOW, tick=False)
@responses.activate
def test_error_classification_preserves_checkpoint(status: int) -> None:
    responses.get(f"{BASE}/clicks/blocked", json={"queryEndTime": "2026-01-08T10:59:00Z", "clicksBlocked": []})
    responses.get(
        f"{BASE}/clicks/blocked",
        status=status,
        json={"message": "Error : Service Id / Credentials authentication failed"} if status == 401 else {},
    )
    harness = Harness()
    expected = RESTClientRetryableError if status >= 429 else HTTPError
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client._retry_wait_seconds",
        return_value=0,
    ):
        with patch("tenacity.nap.time.sleep"):
            with pytest.raises(expected) as error:
                harness.rows()
    if status in (401, 403):
        assert any(pattern in str(error.value) for pattern in harness.source.get_non_retryable_errors())
        assert len(responses.calls) == 2
    else:
        assert len(responses.calls) > 2
    assert harness.manager.save_state.call_count == 1
    assert harness.manager.save_state.call_args.args[0].next_start == "2026-01-08T10:59:00+00:00"
    assert harness.cursor.staged is None


@pytest.mark.parametrize(
    ("status", "schema", "valid", "message", "path"),
    [
        (403, None, True, None, "/v2/siem/clicks/blocked"),
        (403, "messages_blocked", False, "Check access in the TAP dashboard", "/v2/siem/messages/blocked"),
        (200, "threats", True, None, "/v2/siem/all"),
        (200, "campaigns", True, None, "/v2/siem/clicks/blocked"),
        (200, "top_clickers", True, None, "/v2/siem/clicks/blocked"),
    ],
)
def test_credential_probe_status_mapping(
    status: int, schema: str | None, valid: bool, message: str | None, path: str
) -> None:
    response = ScriptedResponse(status=status, json={"queryEndTime": NOW.isoformat()})
    with scripted_network([response]) as network:
        result, error = ProofpointTapSource().validate_credentials(CONFIG, 1, schema)
    assert result is valid
    if message is None:
        assert error is None
    else:
        assert error is not None and message in error
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.path == path
    assert request.query == {"format": ("json",), "sinceSeconds": ("30",)}


def test_unexpected_probe_error_is_not_bad_credentials() -> None:
    with scripted_network([ScriptedResponse(status=400, json={})]):
        with pytest.raises(HTTPError):
            ProofpointTapSource().validate_credentials(CONFIG, 1)


@pytest.mark.parametrize(
    ("resume", "lookups", "saved"),
    [
        (
            None,
            ["threat-a", "gone", "threat-b"],
            [
                ("2026-01-08T09:59:00+00:00", ()),
                ("2026-01-08T09:59:00+00:00", ("threat-a",)),
                ("2026-01-08T09:59:00+00:00", ("threat-a", "gone")),
                ("2026-01-08T09:59:00+00:00", ("threat-a", "gone", "threat-b")),
                ("2026-01-08T10:59:00+00:00", ()),
            ],
        ),
        (
            TapResumeState(next_start="2026-01-08T09:59:00+00:00", end="2026-01-08T11:59:00+00:00", done=("threat-a",)),
            ["gone", "threat-b"],
            [
                ("2026-01-08T09:59:00+00:00", ("threat-a",)),
                ("2026-01-08T09:59:00+00:00", ("threat-a", "gone")),
                ("2026-01-08T09:59:00+00:00", ("threat-a", "gone", "threat-b")),
                ("2026-01-08T10:59:00+00:00", ()),
            ],
        ),
    ],
)
@time_machine.travel(NOW, tick=False)
@responses.activate
def test_threats_resolve_each_siem_threat_once_and_skip_missing(
    resume: TapResumeState | None, lookups: list[str], saved: list[tuple[str, tuple[str, ...]]]
) -> None:
    def siem_all(request: PreparedRequest) -> tuple[int, dict[str, str], str]:
        end = query(request)["interval"][0].split("/")[1]
        payload = {
            "queryEndTime": end,
            "clicksBlocked": [{"id": "click-a", "threatID": "threat-a"}],
            "clicksPermitted": [],
            "messagesBlocked": [
                {"GUID": "message-a", "threatsInfoMap": [{"threatID": "threat-a"}, {"threatID": "gone"}]}
            ],
            "messagesDelivered": [{"GUID": "message-b", "threatsInfoMap": [{"threatID": "threat-b"}]}],
        }
        return 200, {"Content-Type": "application/json"}, json.dumps(payload)

    responses.add_callback(responses.GET, f"{BASE}/all", callback=siem_all)
    for threat_id in ("threat-a", "threat-b"):
        responses.get(
            f"{ROOT}/threat/summary/{threat_id}", json={"id": threat_id, "identifiedAt": "2026-01-01T00:00:00Z"}
        )
    responses.get(f"{ROOT}/threat/summary/gone", status=404, json={})

    harness = Harness(endpoint="threats", resume=resume)
    rows = harness.rows()

    expected_rows = [threat_id for threat_id in lookups if threat_id != "gone"]
    assert [(row["id"], row["query_end_time"]) for row in rows] == [
        (threat_id, datetime(2026, 1, 8, 10, 59, tzinfo=UTC)) for threat_id in expected_rows
    ]
    assert [urlparse(call.request.url or "").path for call in responses.calls] == [
        "/v2/siem/all",
        *[f"/v2/threat/summary/{threat_id}" for threat_id in lookups],
        "/v2/siem/all",
    ]
    assert [(call.args[0].next_start, call.args[0].done) for call in harness.manager.save_state.call_args_list] == saved
    assert harness.response.primary_keys == ["id"]
    assert harness.response.sort_mode is None
    assert harness.cursor.staged == TapCursor(query_end_time="2026-01-08T11:59:00+00:00")


@time_machine.travel(NOW, tick=False)
@responses.activate
def test_campaigns_page_through_one_day_windows_and_merge_details() -> None:
    full_page = [{"id": f"campaign-{i}", "lastUpdatedAt": "2026-01-07T00:00:00Z", "notable": False} for i in range(200)]
    responses.get(f"{ROOT}/campaign/ids", json={"campaigns": full_page})
    responses.get(f"{ROOT}/campaign/ids", json={"campaigns": [{"id": "campaign-0"}, {"id": "campaign-x"}]})
    responses.get(f"{ROOT}/campaign/ids", json={"campaigns": []})
    responses.add_callback(
        responses.GET,
        re.compile(f"{ROOT}/campaign/campaign-.+"),
        callback=lambda request: (
            200,
            {},
            json.dumps({"id": urlparse(request.url or "").path.rsplit("/", 1)[1], "name": "Example"}),
        ),
    )

    harness = Harness(endpoint="campaigns", watermark=NOW - timedelta(days=1, hours=1))
    rows = harness.rows()

    listings = [
        query(call.request) for call in responses.calls if call.request.url and "/campaign/ids" in call.request.url
    ]
    assert [(q["interval"][0], q["page"], q["size"]) for q in listings] == [
        ("2026-01-07T10:59:00+00:00/2026-01-08T10:59:00+00:00", ["1"], ["200"]),
        ("2026-01-07T10:59:00+00:00/2026-01-08T10:59:00+00:00", ["2"], ["200"]),
        ("2026-01-08T10:59:00+00:00/2026-01-08T11:59:00+00:00", ["1"], ["200"]),
    ]
    assert len(rows) == 201
    assert rows[0] == {
        "id": "campaign-0",
        "lastUpdatedAt": "2026-01-07T00:00:00Z",
        "notable": False,
        "name": "Example",
        "query_end_time": datetime(2026, 1, 8, 10, 59, tzinfo=UTC),
    }
    assert rows[-1]["id"] == "campaign-x"
    assert harness.cursor.staged == TapCursor(query_end_time="2026-01-08T11:59:00+00:00")


@pytest.mark.parametrize(
    ("endpoint", "path", "size", "first_page"),
    [
        ("very_attacked_people", "people/vap", 1000, 1),
        ("top_clickers", "people/top-clickers", 200, 1),
        ("top_clickers", "people/top-clickers", 200, 3),
    ],
)
@responses.activate
def test_people_walk_pages_and_key_rows_by_identity(endpoint: str, path: str, size: int, first_page: int) -> None:
    def user(guid: str) -> dict[str, Any]:
        return {"identity": {"guid": guid, "emails": [f"{guid}@example.com"]}, "threatStatistics": {"attackIndex": 1}}

    interval = "2025-10-10T00:00:00Z/2026-01-08T00:00:00Z"
    responses.get(f"{ROOT}/{path}", json={"users": [user(f"user-{i}") for i in range(size)], "interval": interval})
    responses.get(f"{ROOT}/{path}", json={"users": [user("user-0"), user("user-last")], "interval": interval})

    resume = TapResumeState(page=first_page) if first_page > 1 else None
    harness = Harness(endpoint=endpoint, incremental=False, watermark=None, resume=resume)
    rows = harness.rows()

    assert [query(call.request) for call in responses.calls] == [
        {"window": ["90"], "size": [str(size)], "page": [str(first_page)]},
        {"window": ["90"], "size": [str(size)], "page": [str(first_page + 1)]},
    ]
    assert [call.args[0].page for call in harness.manager.save_state.call_args_list] == [first_page + 1, first_page + 2]
    assert len(rows) == size + 1
    assert rows[-1]["guid"] == "user-last"
    assert rows[-1]["interval"] == interval
    assert harness.response.primary_keys == ["guid"]
    assert harness.response.partition_keys is None


@responses.activate
def test_people_user_without_guid_fails() -> None:
    responses.get(f"{ROOT}/people/vap", json={"users": [{"identity": {}}]})
    with pytest.raises(ValueError):
        Harness(endpoint="very_attacked_people", incremental=False, watermark=None).rows()
