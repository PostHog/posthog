import hmac
import json
import base64
import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.naverads import (
    NaverAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.naver_ads import naver_ads as naver_ads_module
from products.warehouse_sources.backend.temporal.data_imports.sources.naver_ads.naver_ads import (
    NaverAdsResumeConfig,
    stats_window,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.naver_ads.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.naver_ads.source import NaverAdsSource

CONFIG = NaverAdsSourceConfig(api_key="example-license", secret_key="example-secret", customer_id=" 1234567 ")
# 12:00 KST on 2026-10-15.
NOW = "2026-10-15T03:00:00Z"


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[None]:
    with time_machine.travel(NOW, tick=False):
        yield


def driver() -> SourceDriver:
    return SourceDriver(NaverAdsSource(), CONFIG)


def ok(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


def stats_responder(
    requests_per_day: dict[str, list[list[str]]], campaign_ids: tuple[str, ...] = ("cmp-1", "cmp-2", "cmp-3")
) -> Any:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/ncc/campaigns":
            return ok([{"nccCampaignId": campaign_id} for campaign_id in campaign_ids])
        assert request.path == "/stats"
        day = json.loads(request.param("timeRange") or "{}")["since"]
        ids = (request.param("ids") or "").split(",")
        requests_per_day.setdefault(day, []).append(ids)
        return ok({"data": [{"id": entity_id, "impCnt": 10, "clkCnt": 1} for entity_id in ids]})

    return respond


def test_requests_carry_a_signature_over_the_path_without_the_query() -> None:
    result = driver().run("campaigns", [ok([{"nccCampaignId": "cmp-1"}])])

    assert result.raised is None
    request = result.requests[0]
    expected = base64.b64encode(
        hmac.new(
            b"example-secret", f"{request.headers['x-timestamp']}.GET./ncc/campaigns".encode(), hashlib.sha256
        ).digest()
    ).decode()
    assert request.param("recordSize") == "1000"
    assert request.headers["x-signature"] == expected
    assert request.headers["x-customer"] == "1234567"
    assert request.headers["x-api-key"] == "example-license"


def test_keyset_pages_drop_the_row_baseSearchId_names_and_stop_on_a_short_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(naver_ads_module, "PAGE_SIZE", 2)

    result = driver().run(
        "campaigns",
        [
            ok([{"nccCampaignId": "cmp-1"}, {"nccCampaignId": "cmp-2"}]),
            ok([{"nccCampaignId": "cmp-2"}, {"nccCampaignId": "cmp-3"}]),
            ok([{"nccCampaignId": "cmp-3"}]),
        ],
    )

    assert result.raised is None
    assert result.params("baseSearchId") == [None, "cmp-2", "cmp-3"]
    assert [row["nccCampaignId"] for row in result.rows] == ["cmp-1", "cmp-2", "cmp-3"]


def test_a_page_that_repeats_its_cursor_fails_instead_of_looping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(naver_ads_module, "PAGE_SIZE", 1)

    result = driver().run("campaigns", always(ok([{"nccCampaignId": "cmp-1"}])))

    assert isinstance(result.raised, ValueError)
    assert len(result.requests) == 2


def test_child_entities_fan_out_per_parent_in_id_order_and_save_each_finished_parent() -> None:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/ncc/campaigns":
            return ok([{"nccCampaignId": "cmp-b"}, {"nccCampaignId": "cmp-a"}])
        if request.path == "/ncc/adgroups":
            campaign = request.param("nccCampaignId")
            return ok([{"nccAdgroupId": f"grp-{campaign}"}])
        assert request.path == "/ncc/ads"
        adgroup = request.param("nccAdgroupId")
        assert request.param("recordSize") is None
        return ok([] if adgroup == "grp-cmp-a" else [{"nccAdId": f"ad-{adgroup}", "nccAdgroupId": adgroup}])

    result = driver().run("ads", respond)

    assert result.raised is None
    assert [request.param("nccCampaignId") for request in result.requests if request.path == "/ncc/adgroups"] == [
        "cmp-a",
        "cmp-b",
    ]
    assert [row["nccAdId"] for row in result.rows] == ["ad-grp-cmp-b"]
    assert result.saved_states == [
        NaverAdsResumeConfig(after_id="grp-cmp-a"),
        NaverAdsResumeConfig(after_id="grp-cmp-b"),
    ]
    assert result.committed_states[-1] == NaverAdsResumeConfig(after_id="grp-cmp-b")
    assert result.completed_state is None


def test_child_entities_resume_after_the_last_finished_parent() -> None:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/ncc/campaigns":
            return ok([{"nccCampaignId": "cmp-1"}])
        if request.path == "/ncc/adgroups":
            return ok([{"nccAdgroupId": "grp-1"}, {"nccAdgroupId": "grp-2"}])
        return ok([{"nccKeywordId": f"kwd-{request.param('nccAdgroupId')}"}])

    result = driver().run("keywords", respond, resume_state=NaverAdsResumeConfig(after_id="grp-1"))

    assert result.raised is None
    assert [request.param("nccAdgroupId") for request in result.requests if request.path == "/ncc/keywords"] == [
        "grp-2"
    ]
    assert [row["nccKeywordId"] for row in result.rows] == ["kwd-grp-2"]


@pytest.mark.parametrize(
    ("last_value", "should_use", "expected_days"),
    [
        # The pipeline applies the schema's lookback before the source sees the watermark.
        (date(2026, 10, 13), True, ["2026-10-13", "2026-10-14", "2026-10-15"]),
        ("2026-10-13", True, ["2026-10-13", "2026-10-14", "2026-10-15"]),
        # A full refresh ignores the stored watermark and reads the whole history window.
        (date(2026, 10, 14), False, None),
    ],
)
def test_stats_windows_start_from_the_watermark_or_the_history_window(
    last_value: Any, should_use: bool, expected_days: list[str] | None
) -> None:
    requests_per_day: dict[str, list[list[str]]] = {}

    result = driver().run(
        "campaign_stats",
        stats_responder(requests_per_day),
        incremental_field="date",
        db_incremental_field_last_value=last_value,
        should_use_incremental_field=should_use,
    )

    assert result.raised is None
    days = list(requests_per_day)
    if expected_days is None:
        assert days[0] == "2025-10-15"
        assert days[-1] == "2026-10-15"
        assert len(days) == 366
    else:
        assert days == expected_days
    first = result.rows[0]
    assert first["date"] == date.fromisoformat(days[0])
    assert {row["id"] for row in result.rows if row["date"] == first["date"]} == {"cmp-1", "cmp-2", "cmp-3"}
    stats_request = next(request for request in result.requests if request.path == "/stats")
    assert json.loads(stats_request.param("fields") or "[]")[:2] == ["impCnt", "clkCnt"]


def test_a_first_sync_starts_on_the_kst_day_of_the_recorded_history_start() -> None:
    inputs = source_inputs("keyword_stats")
    # 20:00 UTC is already the next day in Korea.
    inputs.history_start = datetime(2025, 10, 14, 20, tzinfo=UTC)

    window = stats_window(ENDPOINTS["keyword_stats"], inputs, None, today=date(2026, 10, 15))

    assert (window.start, window.end) == (date(2025, 10, 15), date(2026, 10, 15))


def test_stats_chunk_ids_and_resume_after_the_last_written_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(naver_ads_module, "STATS_IDS_PER_REQUEST", 2)
    requests_per_day: dict[str, list[list[str]]] = {}

    # The last attempt wrote cmp-1 and cmp-2 for 2026-10-14. cmp-1 is gone since, which shifts the chunks.
    result = driver().run(
        "campaign_stats",
        stats_responder(requests_per_day, campaign_ids=("cmp-2", "cmp-3", "cmp-4")),
        resume_state=NaverAdsResumeConfig(
            after_id="cmp-2", stat_date="2026-10-14", window_start="2026-10-13", window_end="2026-10-15"
        ),
    )

    assert result.raised is None
    assert requests_per_day == {
        "2026-10-14": [["cmp-3", "cmp-4"]],
        "2026-10-15": [["cmp-2", "cmp-3"], ["cmp-4"]],
    }
    window = {"window_start": "2026-10-13", "window_end": "2026-10-15"}
    # Each chunk's state persists with that chunk's rows, so a hand-off never re-reads a written chunk.
    assert result.committed_states == [
        NaverAdsResumeConfig(after_id="cmp-2", stat_date="2026-10-14", **window),
        NaverAdsResumeConfig(after_id=None, stat_date="2026-10-15", **window),
        NaverAdsResumeConfig(after_id="cmp-3", stat_date="2026-10-15", **window),
        NaverAdsResumeConfig(after_id=None, stat_date="2026-10-16", **window),
    ]
    assert result.completed_state is None


def test_a_stats_body_without_data_fails_instead_of_syncing_nothing() -> None:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/ncc/campaigns":
            return ok([{"nccCampaignId": "cmp-1"}])
        return ok({"summaryStatResponse": {}})

    result = driver().run(
        "campaign_stats", respond, incremental_field="date", db_incremental_field_last_value="2026-10-15"
    )

    assert isinstance(result.raised, ValueError)
    assert result.rows == []


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_fail_the_sync_without_retrying(status: int) -> None:
    body = {"code": 1018, "title": "No permission to access the resource.", "status": status}

    result = driver().run("campaigns", [ScriptedResponse(status=status, json=body)])

    assert isinstance(result.raised, HTTPError)
    assert "api.searchad.naver.com" in str(result.raised)
    assert len(result.requests) == 1


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (ScriptedResponse(json=[]), (True, None)),
    ],
)
def test_validate_credentials_maps_the_probe_status(
    answer: ScriptedResponse, expected: tuple[bool, str | None]
) -> None:
    with scripted_network(always(answer)) as network:
        valid, message = validate_credentials(CONFIG)

    assert valid is expected[0]
    if expected[1] is None:
        assert message is None
    else:
        assert message is not None and expected[1] in message
    assert network.requests_log[0].headers["x-customer"] == "1234567"


def test_validate_credentials_rejects_a_non_numeric_customer_id_without_a_request() -> None:
    config = NaverAdsSourceConfig(api_key="example-license", secret_key="example-secret", customer_id="acme")

    with scripted_network([]) as network:
        valid, message = NaverAdsSource().validate_credentials(config, team_id=1)

    assert valid is False
    assert message is not None
    assert network.requests_log == []
