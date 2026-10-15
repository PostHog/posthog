from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.scarf import ScarfSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scarf.scarf import (
    INVALID_TOKEN_MESSAGE,
    OWNER_FORMAT_MESSAGE,
    OWNER_MESSAGE,
    ScarfResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scarf.source import ScarfSource

CONFIG = ScarfSourceConfig(api_token="scarf-token", owner="my-org", backfill_days=2)
HEADER = "id,type,package,pixel,version,time,referer,user_agent,origin_latitude,origin_company,dnt,confidence"


@pytest.fixture(autouse=True)
def frozen_today() -> Iterator[None]:
    with time_machine.travel(datetime(2026, 10, 15, 12, tzinfo=UTC), tick=False):
        yield


def csv_response(*rows: str) -> ScriptedResponse:
    return ScriptedResponse(body="\n".join([HEADER, *rows]).encode(), headers={"Content-Type": "text/csv"})


def events_by_day(days: dict[str, list[str]]) -> Any:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        assert request.param("start_date") == request.param("end_date")
        return csv_response(*days[request.param("start_date") or ""])

    return respond


def _driver(config: ScarfSourceConfig = CONFIG) -> SourceDriver:
    return SourceDriver(ScarfSource(), config)


def test_incremental_events_read_one_day_per_request_from_the_watermark_day() -> None:
    result = _driver().run(
        "package_events",
        events_by_day(
            {
                "2026-10-13": ["e1,binary-download,cli,,1.2.0,2026-10-13T08:00:00Z,,curl/8,52.37,Acme,false,0.9"],
                "2026-10-14": [],
                "2026-10-15": ["e2,binary-download,cli,,1.3.0,2026-10-15T01:00:00Z,,pip/24,,,true,"],
            }
        ),
        incremental_field="time",
        db_incremental_field_last_value=datetime(2026, 10, 13, 5, tzinfo=UTC),
    )

    assert result.raised is None
    assert result.paths == ["/v2/packages/my-org/events"] * 3
    assert result.params("start_date") == ["2026-10-13", "2026-10-14", "2026-10-15"]
    assert result.rows == [
        {
            "id": "e1",
            "type": "binary-download",
            "package": "cli",
            "pixel": None,
            "version": "1.2.0",
            "time": "2026-10-13T08:00:00Z",
            "referer": None,
            "user_agent": "curl/8",
            "origin_latitude": 52.37,
            "origin_company": "Acme",
            "dnt": False,
            "confidence": 0.9,
        },
        {
            "id": "e2",
            "type": "binary-download",
            "package": "cli",
            "pixel": None,
            "version": "1.3.0",
            "time": "2026-10-15T01:00:00Z",
            "referer": None,
            "user_agent": "pip/24",
            "origin_latitude": None,
            "origin_company": None,
            "dnt": True,
            "confidence": None,
        },
    ]
    assert result.requests[0].headers["authorization"] == "Bearer scarf-token"


def test_first_sync_reads_the_configured_backfill_and_saves_each_day_before_its_rows() -> None:
    result = _driver().run(
        "tracking_pixel_events",
        events_by_day(
            {
                "2026-10-13": ["v1,pixel-fetch,,px,,2026-10-13T09:00:00Z,https://docs.example.com,,,,,"],
                "2026-10-14": [],
                "2026-10-15": [],
            }
        ),
    )

    assert result.params("start_date") == ["2026-10-13", "2026-10-14", "2026-10-15"]
    assert result.paths[0] == "/v2/tracking-pixels/my-org/events"
    assert result.committed_states[0] == ScarfResumeConfig(day="2026-10-13")


def test_resume_reads_the_saved_day_again_and_continues() -> None:
    result = _driver().run(
        "package_events",
        events_by_day({"2026-10-14": ["e1,binary-download,cli,,1.2.0,2026-10-14T08:00:00Z,,,,,,"], "2026-10-15": []}),
        resume_state=ScarfResumeConfig(day="2026-10-14"),
    )

    assert result.params("start_date") == ["2026-10-14", "2026-10-15"]
    assert [row["id"] for row in result.rows] == ["e1"]


def test_lists_follow_the_next_link_and_refuse_one_that_leaves_scarf() -> None:
    result = _driver().run(
        "packages",
        [
            ScriptedResponse(
                json={
                    "results": [{"id": "p1", "name": "cli"}],
                    "_links": {"next": "https://api.scarf.sh/v2/packages/my-org?after=cli&per_page=100"},
                }
            ),
            ScriptedResponse(
                json={"results": [{"id": "p2", "name": "sdk"}], "_links": {"next": "https://evil.example.com/steal"}}
            ),
        ],
    )

    assert [row["id"] for row in result.rows] == ["p1", "p2"]
    assert result.params("after") == [None, "cli"]
    assert result.params("per_page") == ["100", "100"]
    assert result.raised is not None
    assert all(request.origin == "https://api.scarf.sh" for request in result.requests)


def test_company_rollup_reads_one_csv_export() -> None:
    body = "company_name,company_domain,funnel_stage,total_events\nAcme,acme.example.com,experimentation,12\n"

    result = _driver().run("company_rollup", [ScriptedResponse(body=body.encode())])

    assert result.paths == ["/v2/packages/my-org/company-rollup"]
    assert result.rows == [
        {
            "company_name": "Acme",
            "company_domain": "acme.example.com",
            "funnel_stage": "experimentation",
            "total_events": "12",
        }
    ]


def test_an_export_without_runs_left_fails_with_the_status_the_source_maps() -> None:
    result = _driver().run(
        "package_events",
        always(ScriptedResponse(status=402, json={"error": "The organization has no Runs remaining."})),
        incremental_field="time",
        db_incremental_field_last_value=datetime(2026, 10, 15, tzinfo=UTC),
    )

    assert result.raised is not None
    assert "402 Client Error" in str(result.raised)


@pytest.mark.parametrize(
    ("status", "expected"),
    [(200, None), (401, INVALID_TOKEN_MESSAGE), (404, OWNER_MESSAGE)],
)
def test_validate_credentials_maps_scarf_answers(status: int, expected: str | None) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json={"results": []}))) as network:
        assert ScarfSource().validate_credentials(CONFIG, team_id=1) == (expected is None, expected)

    assert network.requests_log[0].path == "/v2/packages/my-org"


def test_an_owner_that_changes_the_path_is_refused_without_a_request() -> None:
    config = ScarfSourceConfig(api_token="scarf-token", owner="../users/me")

    with scripted_network(always(ScriptedResponse(status=200, json={}))) as network:
        assert ScarfSource().validate_credentials(config, team_id=1) == (False, OWNER_FORMAT_MESSAGE)

    assert network.requests_log == []
