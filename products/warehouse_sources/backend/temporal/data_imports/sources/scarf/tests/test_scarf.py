from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.scarf import ScarfSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scarf import scarf as scarf_transport
from products.warehouse_sources.backend.temporal.data_imports.sources.scarf.scarf import (
    BACKFILL_MESSAGE,
    OWNER_FORMAT_MESSAGE,
    OWNER_MESSAGE,
    ScarfExportCursor,
    ScarfResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scarf.source import ScarfSource

CONFIG = ScarfSourceConfig(api_token="scarf-token", owner="my-org", backfill_days=2)
HEADER = "id,type,package,version,time,origin_latitude,origin_company,dnt,confidence"


@pytest.fixture(autouse=True)
def frozen_today() -> Iterator[None]:
    with time_machine.travel(datetime(2026, 10, 15, 12, tzinfo=UTC), tick=False):
        yield


def events_by_day(days: dict[str, list[str]]) -> Any:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        assert request.param("start_date") == request.param("end_date")
        rows = days[request.param("start_date") or ""]
        return ScriptedResponse(body="\n".join([HEADER, *rows]).encode(), headers={"Content-Type": "text/csv"})

    return respond


def cursor(stored: ScarfExportCursor | None = None) -> SourceCursorManager[ScarfExportCursor]:
    return SourceCursorManager(ScarfExportCursor, stored, ScarfSource())


def rows_of(result: Any) -> list[dict[str, Any]]:
    return [row for table in result.items for row in table.to_pylist()]


def _driver(config: ScarfSourceConfig = CONFIG) -> SourceDriver:
    return SourceDriver(ScarfSource(), config)


def test_incremental_events_export_one_day_per_request_and_hand_over_whole_days() -> None:
    manager = cursor()
    result = _driver().run(
        "package_events",
        events_by_day(
            {
                "2026-10-13": [
                    "e1,binary-download,cli,1.2,2026-10-13T08:00:00Z,52.37,Zürich Software GmbH,false,0.9",
                    "e2,binary-download,cli,NA,2026-10-13 09:00:00,,,true,",
                ],
                "2026-10-14": [],
                "2026-10-15": ["e3,binary-download,cli,1.3,2026-10-15T01:00:00Z,,,,"],
            }
        ),
        incremental_field="time",
        db_incremental_field_last_value=datetime(2026, 10, 13, 5, tzinfo=UTC),
        source_cursor=manager,
    )

    assert result.raised is None
    assert result.paths == ["/v2/packages/my-org/events"] * 3
    assert result.params("start_date") == ["2026-10-13", "2026-10-14", "2026-10-15"]
    assert len(result.items) == 2
    assert rows_of(result)[0] == {
        "id": "e1",
        "type": "binary-download",
        "package": "cli",
        "version": "1.2",
        "time": datetime(2026, 10, 13, 8, tzinfo=UTC),
        "origin_latitude": 52.37,
        "origin_company": "Zürich Software GmbH",
        "dnt": False,
        "confidence": 0.9,
    }
    assert [row["dnt"] for row in rows_of(result)] == [False, True, None]
    assert rows_of(result)[1]["version"] == "NA"
    assert rows_of(result)[1]["time"] == datetime(2026, 10, 13, 9, tzinfo=UTC)
    assert result.committed_states[0] == ScarfResumeConfig(day="2026-10-14")
    assert manager.staged == ScarfExportCursor(next_day="2026-10-15")
    assert result.requests[0].headers["authorization"] == "Bearer scarf-token"


def test_the_export_cursor_wins_over_the_watermark_so_idle_days_are_not_exported_again() -> None:
    manager = cursor(ScarfExportCursor(next_day="2026-10-14"))
    result = _driver().run(
        "tracking_pixel_events",
        events_by_day({"2026-10-14": [], "2026-10-15": []}),
        incremental_field="time",
        db_incremental_field_last_value=datetime(2026, 9, 1, tzinfo=UTC),
        source_cursor=manager,
    )

    assert result.params("start_date") == ["2026-10-14", "2026-10-15"]
    assert result.paths[0] == "/v2/tracking-pixels/my-org/events"
    assert manager.staged == ScarfExportCursor(next_day="2026-10-15")


def test_a_configured_lookback_moves_the_export_day_back() -> None:
    result = _driver().run(
        "package_events",
        events_by_day({"2026-10-12": [], "2026-10-13": [], "2026-10-14": [], "2026-10-15": []}),
        incremental_field="time",
        db_incremental_field_last_value=datetime(2026, 10, 12, tzinfo=UTC),
        db_incremental_field_last_value_before_lookback=datetime(2026, 10, 14, tzinfo=UTC),
        source_cursor=cursor(ScarfExportCursor(next_day="2026-10-14")),
    )

    assert result.params("start_date")[0] == "2026-10-12"


@pytest.mark.parametrize(("backfill_days", "first_day"), [(2, "2026-10-13"), (0, "2026-10-15")])
def test_a_full_refresh_reads_the_backfill_window(backfill_days: int, first_day: str) -> None:
    config = ScarfSourceConfig(api_token="scarf-token", owner="my-org", backfill_days=backfill_days)
    days: dict[str, list[str]] = {"2026-10-13": [], "2026-10-14": [], "2026-10-15": []}

    result = _driver(config).run("package_events", events_by_day(days), source_cursor=cursor())

    assert result.params("start_date")[0] == first_day
    assert result.params("start_date")[-1] == "2026-10-15"


def test_resume_starts_at_the_saved_day_without_reading_the_last_day_again() -> None:
    result = _driver().run(
        "package_events",
        events_by_day({"2026-10-14": ["e1,binary-download,cli,1.2,2026-10-14T08:00:00Z,,,,"], "2026-10-15": []}),
        resume_state=ScarfResumeConfig(day="2026-10-14"),
        source_cursor=cursor(),
    )

    assert result.params("start_date") == ["2026-10-14", "2026-10-15"]
    assert [row["id"] for row in rows_of(result)] == ["e1"]


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


def test_company_rollup_counts_are_numbers() -> None:
    # A byte order mark and quoted names must not change the column names the types are keyed on.
    body = '\ufeff"company_name","company_domain","funnel_stage","total_events","total_views"\nAcme,acme.example.com,experimentation,12,\n'

    result = _driver().run("company_rollup", [ScriptedResponse(body=body.encode())])

    assert result.paths == ["/v2/packages/my-org/company-rollup"]
    assert rows_of(result) == [
        {
            "company_name": "Acme",
            "company_domain": "acme.example.com",
            "funnel_stage": "experimentation",
            "total_events": 12,
            "total_views": None,
        }
    ]


def test_an_export_without_runs_left_fails_with_the_status_the_source_maps() -> None:
    result = _driver().run(
        "package_events",
        always(ScriptedResponse(status=402, json={"error": "The organization has no Runs remaining."})),
        incremental_field="time",
        db_incremental_field_last_value=datetime(2026, 10, 15, tzinfo=UTC),
        source_cursor=cursor(),
    )

    assert result.raised is not None
    assert "402 Client Error" in str(result.raised)


def test_a_day_too_large_to_hand_over_whole_fails_with_a_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scarf_transport, "MAX_EXPORT_BYTES", 100)
    rows = [f"e{i},binary-download,cli,1.2,2026-10-15T01:00:00Z,,,," for i in range(10)]

    result = _driver().run(
        "package_events",
        events_by_day({"2026-10-15": rows}),
        incremental_field="time",
        db_incremental_field_last_value=datetime(2026, 10, 15, tzinfo=UTC),
        source_cursor=cursor(),
    )

    assert isinstance(result.raised, ValueError)
    assert str(result.raised) == scarf_transport.EXPORT_TOO_LARGE_MESSAGE
    assert result.items == []


@pytest.mark.parametrize(("status", "expected"), [(404, OWNER_MESSAGE)])
def test_validate_credentials_maps_scarf_answers(status: int, expected: str | None) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json={"results": []}))) as network:
        assert ScarfSource().validate_credentials(CONFIG, team_id=1) == (expected is None, expected)

    assert network.requests_log[0].path == "/v2/packages/my-org"


@pytest.mark.parametrize(
    ("owner", "backfill_days", "expected"),
    [("../users/me", 2, OWNER_FORMAT_MESSAGE), ("my-org", -1, BACKFILL_MESSAGE), ("my-org", 10**9, BACKFILL_MESSAGE)],
)
def test_bad_settings_are_refused_without_a_request(owner: str, backfill_days: int, expected: str) -> None:
    config = ScarfSourceConfig(api_token="scarf-token", owner=owner, backfill_days=backfill_days)

    with scripted_network(always(ScriptedResponse(status=200, json={}))) as network:
        assert ScarfSource().validate_credentials(config, team_id=1) == (False, expected)

    assert network.requests_log == []
