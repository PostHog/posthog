from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.vercel import vercel
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.settings import VERCEL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.vercel import (
    BILLING_BACKFILL_DAYS,
    PAGE_SIZE,
    VercelResumeConfig,
    _billing_window_start,
    _build_params,
    _cursor_from_page,
    _floor_to_day,
    _focus_charge_id,
    _iso8601_utc,
    _ms_to_iso8601,
    _should_stop_desc,
    get_billing_rows,
    get_rows,
    validate_credentials,
    vercel_source,
)


class _FakeResumableManager:
    def __init__(self, state: VercelResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[VercelResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> VercelResumeConfig | None:
        return self._state

    def save_state(self, data: VercelResumeConfig) -> None:
        self.saved.append(data)


def _patch_fetch(monkeypatch: Any, responses: list[dict]) -> list[str]:
    """Replace _fetch_page with a queue that returns canned pages in order, recording each URL."""
    calls: list[str] = []
    queue = list(responses)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        calls.append(url)
        return queue.pop(0)

    monkeypatch.setattr(vercel, "_fetch_page", fake_fetch)
    return calls


def _collect(endpoint: str, manager: _FakeResumableManager, monkeypatch: Any, responses: list[dict], **kwargs: Any):
    calls = _patch_fetch(monkeypatch, responses)
    rows: list[dict] = []
    for table in get_rows(
        access_token="t",
        endpoint=endpoint,
        team_id=kwargs.get("team_id"),
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        should_use_incremental_field=kwargs.get("should_use_incremental_field", False),
        db_incremental_field_last_value=kwargs.get("db_incremental_field_last_value"),
        incremental_field=kwargs.get("incremental_field"),
    ):
        rows.extend(table.to_pylist())
    return rows, calls


class TestBuildParams:
    @parameterized.expand(
        [
            ("default", "deployments", None, None, None, {"limit": PAGE_SIZE}),
            ("team_scoped_with_team", "deployments", "team_1", None, None, {"limit": PAGE_SIZE, "teamId": "team_1"}),
            # /v2/teams lists resources visible to the token itself, so teamId must not be appended.
            ("not_team_scoped_ignores_team", "teams", "team_1", None, None, {"limit": PAGE_SIZE}),
            ("since_and_until", "deployments", None, 123, 456, {"limit": PAGE_SIZE, "since": 123, "until": 456}),
            # projects has no since_param, so a cursor value must not become a query filter.
            ("no_since_param_drops_since", "projects", None, 123, None, {"limit": PAGE_SIZE}),
            # Without withPayload the response carries only each event's summary text, so the
            # payload column lands empty and the table loses the detail it exists for.
            (
                "events_requests_the_payload",
                "events",
                "team_1",
                None,
                None,
                {"limit": PAGE_SIZE, "teamId": "team_1", "withPayload": "true"},
            ),
            # events' since/until must be ISO 8601 strings, not raw Unix-ms integers — Vercel's
            # OpenAPI spec types them as strings and 400s a raw ms value (unlike deployments above,
            # which documents since/until as numbers).
            (
                "events_since_and_until_as_iso",
                "events",
                None,
                123,
                456,
                {
                    "limit": PAGE_SIZE,
                    "withPayload": "true",
                    "since": "1970-01-01T00:00:00.123Z",
                    "until": "1970-01-01T00:00:00.456Z",
                },
            ),
        ]
    )
    def test_build_params(
        self,
        _name: str,
        endpoint: str,
        team_id: str | None,
        since_value: Any,
        until: int | None,
        expected: dict[str, Any],
    ) -> None:
        assert _build_params(VERCEL_ENDPOINTS[endpoint], team_id, since_value, until) == expected


class TestShouldStopDesc:
    @parameterized.expand(
        [
            ("page_crosses_watermark", [{"created": 300}, {"created": 100}], "created", 150, True),
            ("equal_to_watermark_stops", [{"created": 150}], "created", 150, True),
            ("all_above_watermark", [{"created": 300}, {"created": 200}], "created", 150, False),
            ("no_cutoff", [{"created": 300}], "created", None, False),
            ("no_field", [{"created": 300}], None, 150, False),
            ("empty_items", [], "created", 150, False),
            ("missing_field_value_ignored", [{"other": 1}], "created", 150, False),
        ]
    )
    def test_should_stop_desc(
        self, _name: str, items: list[dict], field_name: str | None, cutoff: Any, expected: bool
    ) -> None:
        assert _should_stop_desc(items, field_name, cutoff) is expected


class TestCursorFromPage:
    @parameterized.expand(
        [
            # The oldest value bounds the next page. Taking the newest would re-request page one.
            ("oldest_wins", [{"createdAt": 300}, {"createdAt": 100}, {"createdAt": 200}], 100),
            ("single_row", [{"createdAt": 42}], 42),
            ("ignores_rows_missing_the_field", [{"createdAt": 300}, {"other": 1}], 300),
            ("ignores_non_integer_values", [{"createdAt": "300"}, {"createdAt": 200}], 200),
            ("no_usable_values", [{"other": 1}], None),
            ("empty_page", [], None),
        ]
    )
    def test_cursor_from_page(self, _name: str, items: list[dict[str, Any]], expected: int | None) -> None:
        assert _cursor_from_page(items, "createdAt") == expected


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    def test_status_mapping(self, status: int, expected_ok: bool) -> None:
        response = requests.Response()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(vercel, "make_tracked_session", lambda *a, **k: session):
            ok, error = validate_credentials("token")

        assert ok is expected_ok, f"status={status}"
        assert (error is None) is expected_ok, f"status={status}"

    def test_request_exception_returns_retry_message_without_leaking_raw_error(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(vercel, "make_tracked_session", lambda *a, **k: session)

        ok, error = validate_credentials("token")
        assert ok is False
        assert error == vercel._VERCEL_UNREACHABLE_ERROR
        assert "boom" not in (error or "")

    @parameterized.expand([(429,), (500,), (503,)])
    def test_transient_status_returns_retry_message_not_token_advice(self, status: int) -> None:
        response = requests.Response()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(vercel, "make_tracked_session", lambda *a, **k: session):
            ok, error = validate_credentials("token")

        assert ok is False
        assert error == vercel._VERCEL_UNREACHABLE_ERROR
        # A transient Vercel-side error must not tell the user to fix their (possibly valid) token.
        assert "Check that it's a valid token" not in (error or "")

    def test_unexpected_status_does_not_leak_raw_status_code(self) -> None:
        response = requests.Response()
        response.status_code = 404
        session = MagicMock()
        session.get.return_value = response
        with patch.object(vercel, "make_tracked_session", lambda *a, **k: session):
            ok, error = validate_credentials("token")

        assert ok is False
        assert error is not None
        assert "Vercel API error" not in error
        assert "404" not in error


class TestGetRows:
    def test_full_refresh_follows_until_cursor_across_pages(self, monkeypatch: Any) -> None:
        responses = [
            {"deployments": [{"uid": "1", "created": 300}, {"uid": "2", "created": 200}], "pagination": {"next": 200}},
            {"deployments": [{"uid": "3", "created": 100}], "pagination": {"next": None}},
        ]
        rows, calls = _collect("deployments", _FakeResumableManager(), monkeypatch, responses)

        assert [r["uid"] for r in rows] == ["1", "2", "3"]
        assert "until=" not in calls[0]
        assert "until=200" in calls[1]

    def test_uses_response_data_key_per_endpoint(self, monkeypatch: Any) -> None:
        responses = [{"projects": [{"id": "p1"}, {"id": "p2"}], "pagination": {"next": None}}]
        rows, _ = _collect("projects", _FakeResumableManager(), monkeypatch, responses)
        assert [r["id"] for r in rows] == ["p1", "p2"]

    def test_incremental_sends_since_and_stops_at_watermark(self, monkeypatch: Any) -> None:
        responses = [
            {"deployments": [{"uid": "1", "created": 300}, {"uid": "2", "created": 200}], "pagination": {"next": 200}},
            # 120 <= watermark(150): stop after this page rather than walking older history.
            {"deployments": [{"uid": "3", "created": 120}], "pagination": {"next": 120}},
            {"deployments": [{"uid": "4", "created": 50}], "pagination": {"next": None}},
        ]
        rows, calls = _collect(
            "deployments",
            _FakeResumableManager(),
            monkeypatch,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=150,
        )

        assert [r["uid"] for r in rows] == ["1", "2", "3"]
        assert "since=150" in calls[0]
        assert len(calls) == 2

    def test_stops_when_cursor_does_not_advance(self, monkeypatch: Any) -> None:
        # An endpoint that ignores `until` re-serves the same cursor; stop instead of looping forever.
        responses = [
            {"deployments": [{"uid": "1", "created": 300}], "pagination": {"next": 300}},
            {"deployments": [{"uid": "9", "created": 300}], "pagination": {"next": 300}},
        ]
        rows, calls = _collect("deployments", _FakeResumableManager(), monkeypatch, responses)

        assert [r["uid"] for r in rows] == ["1", "9"]
        assert len(calls) == 2

    def test_resumes_from_saved_until_cursor(self, monkeypatch: Any) -> None:
        responses = [{"deployments": [{"uid": "1", "created": 400}], "pagination": {"next": None}}]
        manager = _FakeResumableManager(VercelResumeConfig(until=500))
        rows, calls = _collect("deployments", manager, monkeypatch, responses)

        assert [r["uid"] for r in rows] == ["1"]
        assert "until=500" in calls[0]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        responses = [{"deployments": [], "pagination": {"next": None}}]
        rows, calls = _collect("deployments", _FakeResumableManager(), monkeypatch, responses)
        assert rows == []
        assert len(calls) == 1

    def test_events_pages_without_a_pagination_envelope(self, monkeypatch: Any) -> None:
        # /v3/events returns rows but no `pagination` object. Without the derived cursor the walk
        # ends after page one and the table silently caps at a single page of history forever.
        responses: list[dict] = [
            {"events": [{"id": "e1", "createdAt": 300}, {"id": "e2", "createdAt": 200}]},
            {"events": [{"id": "e3", "createdAt": 100}]},
            {"events": []},
        ]
        rows, calls = _collect("events", _FakeResumableManager(), monkeypatch, responses)

        assert [r["id"] for r in rows] == ["e1", "e2", "e3"]
        assert "until=" not in calls[0]
        # The oldest row on each page bounds the next, so page two asks for until=200, not 300 —
        # encoded as the ISO string events requires, not the raw ms integer.
        assert "until=1970-01-01T00%3A00%3A00.200Z" in calls[1]
        assert "until=1970-01-01T00%3A00%3A00.100Z" in calls[2]

    def test_events_stop_when_a_whole_page_shares_one_timestamp(self, monkeypatch: Any) -> None:
        # The derived cursor can't advance past a page whose rows share a timestamp; the walk has
        # to end there rather than re-request the same page forever.
        responses = [
            {"events": [{"id": "e1", "createdAt": 500}, {"id": "e2", "createdAt": 500}]},
            {"events": [{"id": "e3", "createdAt": 500}]},
        ]
        rows, calls = _collect("events", _FakeResumableManager(), monkeypatch, responses)

        assert [r["id"] for r in rows] == ["e1", "e2", "e3"]
        assert len(calls) == 2

    def test_events_incremental_sends_since_and_stops_at_watermark(self, monkeypatch: Any) -> None:
        responses = [
            {"events": [{"id": "e1", "createdAt": 300}, {"id": "e2", "createdAt": 200}]},
            {"events": [{"id": "e3", "createdAt": 120}]},
            {"events": [{"id": "e4", "createdAt": 50}]},
        ]
        rows, calls = _collect(
            "events",
            _FakeResumableManager(),
            monkeypatch,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=150,
        )

        assert [r["id"] for r in rows] == ["e1", "e2", "e3"]
        assert "since=1970-01-01T00%3A00%3A00.150Z" in calls[0]
        assert len(calls) == 2

    def test_mid_page_yield_checkpoints_current_page_not_next(self, monkeypatch: Any) -> None:
        # Regression: a mid-page yield must checkpoint the cursor for the CURRENT page, not the
        # next one. Page two crosses the batcher's 2000-row chunk, so the batch yields while the
        # rest of page two is still unprocessed. Saving the next cursor (400) here would advance
        # the watermark past those rows and silently skip them after a crash/resume; the checkpoint
        # must stay at page two's own cursor (200) so resume re-fetches it (dedup handles the
        # already-yielded rows).
        responses: list[dict] = [
            {"deployments": [{"uid": "a", "created": 100}, {"uid": "b", "created": 99}], "pagination": {"next": 200}},
            {
                "deployments": [{"uid": str(i), "created": 100000 - i} for i in range(2500)],
                "pagination": {"next": 400},
            },
            {"deployments": [], "pagination": {"next": None}},
        ]
        manager = _FakeResumableManager()
        rows, _ = _collect("deployments", manager, monkeypatch, responses)

        assert len(rows) == 2502
        assert manager.saved == [VercelResumeConfig(until=200)]


def _collect_fanout(monkeypatch: Any, responses: list[dict], team_id: str | None = None):
    calls = _patch_fetch(monkeypatch, responses)
    rows: list[dict] = []
    for table in vercel.get_fanout_rows(access_token="t", endpoint="check_runs", team_id=team_id, logger=MagicMock()):
        rows.extend(table.to_pylist())
    return rows, calls


class TestGetFanoutRows:
    def test_fans_out_one_child_request_per_parent_deployment(self, monkeypatch: Any) -> None:
        responses: list[dict] = [
            {
                "deployments": [{"uid": "d1", "created": 200}, {"uid": "d2", "created": 100}],
                "pagination": {"next": None},
            },
            {"runs": [{"id": "r1", "deploymentId": "d1"}]},
            {"runs": [{"id": "r2", "deploymentId": "d2"}, {"id": "r3", "deploymentId": "d2"}]},
        ]
        rows, calls = _collect_fanout(monkeypatch, responses, team_id="team_1")

        assert [r["id"] for r in rows] == ["r1", "r2", "r3"]
        # The parent is paged from the deployments endpoint; each child request fills the deployment
        # id into the check-runs path and carries teamId.
        assert "/v6/deployments" in calls[0]
        assert "/v2/deployments/d1/check-runs" in calls[1]
        assert "/v2/deployments/d2/check-runs" in calls[2]
        assert "teamId=team_1" in calls[1]
        # The check-runs endpoint documents no limit/pagination params, so the shared `limit` must
        # not be appended to the child request.
        assert "limit=" not in calls[1]

    def test_deployment_with_no_check_runs_still_visits_every_parent(self, monkeypatch: Any) -> None:
        responses: list[dict] = [
            {
                "deployments": [{"uid": "d1", "created": 200}, {"uid": "d2", "created": 100}],
                "pagination": {"next": None},
            },
            {"runs": []},
            {"runs": [{"id": "r2", "deploymentId": "d2"}]},
        ]
        rows, calls = _collect_fanout(monkeypatch, responses)

        assert [r["id"] for r in rows] == ["r2"]
        assert len(calls) == 3

    def test_parent_row_missing_the_fan_out_field_is_skipped(self, monkeypatch: Any) -> None:
        # A deployment row without `uid` can't seed a child path; skip it rather than crash the sync.
        responses: list[dict] = [
            {"deployments": [{"uid": "d1", "created": 200}, {"created": 100}], "pagination": {"next": None}},
            {"runs": [{"id": "r1", "deploymentId": "d1"}]},
        ]
        rows, calls = _collect_fanout(monkeypatch, responses)

        assert [r["id"] for r in rows] == ["r1"]
        # Only the uid-bearing parent issues a child request.
        assert len(calls) == 2

    def test_fans_out_across_every_parent_page(self, monkeypatch: Any) -> None:
        # The parent deployments list paginates; the fan-out must visit deployments from every page,
        # not silently cap the child table at the first page of parents.
        responses: list[dict] = [
            {"deployments": [{"uid": "d1", "created": 300}], "pagination": {"next": 300}},
            {"runs": [{"id": "r1", "deploymentId": "d1"}]},
            {"deployments": [{"uid": "d2", "created": 100}], "pagination": {"next": None}},
            {"runs": [{"id": "r2", "deploymentId": "d2"}]},
        ]
        rows, calls = _collect_fanout(monkeypatch, responses)

        assert [r["id"] for r in rows] == ["r1", "r2"]
        # Page two of the parent is requested with the first page's cursor.
        assert "until=300" in calls[2]


class TestVercelSource:
    @parameterized.expand(
        [
            ("deployments", "uid"),
            ("events", "id"),
            ("projects", "id"),
            ("teams", "id"),
            ("domains", "id"),
            ("aliases", "uid"),
            ("check_runs", "id"),
        ]
    )
    def test_source_response_primary_key_and_sort(self, endpoint: str, expected_pk: str) -> None:
        response = vercel_source(
            access_token="t",
            endpoint=endpoint,
            team_id=None,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == [expected_pk]
        assert response.sort_mode == "desc"

    def test_billing_source_response_is_incremental_merge(self) -> None:
        # billing_charges merges on the synthesized `id`, yields ascending, and partitions by the
        # charge period — unlike the descending, unpartitioned cursor endpoints above.
        response = vercel_source(
            access_token="t",
            endpoint="billing_charges",
            team_id=None,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == "billing_charges"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["charge_period_start"]
        assert response.partition_mode == "datetime"


class _FakeStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.closed = False

    def iter_lines(self, decode_unicode: bool = False) -> Iterator[str]:
        yield from self._lines

    def close(self) -> None:
        self.closed = True


class TestIso8601Utc:
    def test_formats_as_utc_z_with_millis(self) -> None:
        formatted = _iso8601_utc(datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC))
        assert formatted == "2025-01-02T03:04:05.000Z"


class TestMsToIso8601:
    @parameterized.expand(
        [
            ("whole_second", 1700000000000, "2023-11-14T22:13:20.000Z"),
            # Millisecond digits must survive, not just the second — a truncated cursor would
            # under-report `until` and re-request rows the previous page already yielded.
            ("preserves_millis", 1699999999123, "2023-11-14T22:13:19.123Z"),
            ("epoch", 0, "1970-01-01T00:00:00.000Z"),
        ]
    )
    def test_ms_to_iso8601(self, _name: str, ms: int, expected: str) -> None:
        assert _ms_to_iso8601(ms) == expected


class TestFocusChargeId:
    def test_stable_when_only_amounts_change(self) -> None:
        # A restated charge (same dimensions, different measures) must keep its id so merge updates
        # it in place instead of inserting a duplicate.
        base = {
            "ChargePeriodStart": "2025-01-01T00:00:00.000Z",
            "ServiceName": "Functions",
            "RegionId": "iad1",
            "Tags": {"ProjectId": "p_1"},
        }
        first = _focus_charge_id({**base, "BilledCost": 1.0, "EffectiveCost": 0.9, "ConsumedQuantity": 10})
        restated = _focus_charge_id({**base, "BilledCost": 2.0, "EffectiveCost": 1.8, "ConsumedQuantity": 20})
        assert first == restated

    @parameterized.expand(
        [
            ("service", {"ServiceName": "Bandwidth"}),
            ("region", {"RegionId": "sfo1"}),
            ("period", {"ChargePeriodStart": "2025-01-02T00:00:00.000Z"}),
            ("project_tag", {"Tags": {"ProjectId": "p_2"}}),
        ]
    )
    def test_distinct_when_a_dimension_changes(self, _name: str, override: dict[str, Any]) -> None:
        base = {
            "ChargePeriodStart": "2025-01-01T00:00:00.000Z",
            "ServiceName": "Functions",
            "RegionId": "iad1",
            "Tags": {"ProjectId": "p_1"},
            "BilledCost": 1.0,
        }
        assert _focus_charge_id(base) != _focus_charge_id({**base, **override})

    def test_missing_dimension_does_not_collide_with_empty_string(self) -> None:
        # A key present as null must not hash the same as the same key set to "".
        assert _focus_charge_id({"RegionId": None}) != _focus_charge_id({"RegionId": ""})


class TestBillingWindowStart:
    def test_full_refresh_goes_back_the_backfill_window(self) -> None:
        now = datetime(2026, 6, 15, 9, 30, tzinfo=UTC)
        start = _billing_window_start(should_use_incremental_field=False, db_incremental_field_last_value=None, now=now)
        assert start == _floor_to_day(now) - timedelta(days=BILLING_BACKFILL_DAYS)

    def test_incremental_reads_from_the_day_floored_watermark(self) -> None:
        now = datetime(2026, 6, 15, 9, 30, tzinfo=UTC)
        watermark = datetime(2026, 6, 10, 14, 45, tzinfo=UTC)
        start = _billing_window_start(
            should_use_incremental_field=True, db_incremental_field_last_value=watermark, now=now
        )
        assert start == datetime(2026, 6, 10, tzinfo=UTC)

    def test_watermark_is_capped_at_the_one_year_window(self) -> None:
        # A stale watermark older than the backfill window can't push `from` past Vercel's cap.
        now = datetime(2026, 6, 15, 9, 30, tzinfo=UTC)
        stale = datetime(2024, 1, 1, tzinfo=UTC)
        start = _billing_window_start(should_use_incremental_field=True, db_incremental_field_last_value=stale, now=now)
        assert start == _floor_to_day(now) - timedelta(days=BILLING_BACKFILL_DAYS)


class TestGetBillingRows:
    def _collect(
        self, monkeypatch: Any, response: _FakeStreamResponse, team_id: str | None, **kwargs: Any
    ) -> tuple[list[dict], str]:
        captured: dict[str, str] = {}

        def fake_open(session: Any, url: str, headers: dict[str, str], logger: Any) -> _FakeStreamResponse:
            captured["url"] = url
            return response

        monkeypatch.setattr(vercel, "make_tracked_session", lambda *a, **k: MagicMock())
        monkeypatch.setattr(vercel, "_open_billing_stream", fake_open)

        rows: list[dict] = []
        for table in get_billing_rows("token", "billing_charges", team_id, MagicMock(), **kwargs):
            rows.extend(table.to_pylist())
        return rows, captured["url"]

    def test_parses_jsonl_stamps_id_and_sorts_ascending(self, monkeypatch: Any) -> None:
        response = _FakeStreamResponse(
            [
                '{"ChargePeriodStart": "2025-01-03T00:00:00.000Z", "ServiceName": "Functions"}',
                "",
                '{"ChargePeriodStart": "2025-01-01T00:00:00.000Z", "ServiceName": "Bandwidth"}',
            ]
        )
        rows, url = self._collect(monkeypatch, response, team_id="team_9")

        # Blank line skipped, and rows arrive oldest-first regardless of stream order.
        assert [r["ChargePeriodStart"] for r in rows] == [
            "2025-01-01T00:00:00.000Z",
            "2025-01-03T00:00:00.000Z",
        ]
        assert all(r["id"] for r in rows)
        assert "teamId=team_9" in url
        assert "from=" in url and "to=" in url
        assert response.closed is True

    def test_omits_team_id_when_not_set(self, monkeypatch: Any) -> None:
        _, url = self._collect(monkeypatch, _FakeStreamResponse([]), team_id=None)
        assert "teamId" not in url

    def test_empty_stream_yields_no_rows(self, monkeypatch: Any) -> None:
        rows, _ = self._collect(monkeypatch, _FakeStreamResponse([]), team_id="team_1")
        assert rows == []
