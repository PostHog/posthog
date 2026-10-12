from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.vercel import vercel
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.settings import VERCEL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.vercel import (
    PAGE_SIZE,
    VercelResumeConfig,
    _billing_window_start,
    _build_params,
    _cursor_from_page,
    _focus_charge_id,
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

    @parameterized.expand([(400,), (401,), (404,)])
    def test_credential_rejection_status_tells_the_user_to_replace_the_token(self, status: int) -> None:
        response = requests.Response()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(vercel, "make_tracked_session", lambda *a, **k: session):
            ok, error = validate_credentials("token")

        assert ok is False
        assert error == vercel._VERCEL_INVALID_TOKEN_ERROR

    def test_non_ascii_token_is_rejected_without_a_request(self) -> None:
        session = MagicMock()
        with patch.object(vercel, "make_tracked_session", lambda *a, **k: session):
            ok, error = validate_credentials("tok\u00e9n")

        assert ok is False
        assert error == vercel._VERCEL_UNSUPPORTED_CHARACTER_ERROR
        assert session.get.call_count == 0

    def test_unexpected_status_does_not_leak_raw_status_code(self) -> None:
        response = requests.Response()
        response.status_code = 418
        session = MagicMock()
        session.get.return_value = response
        with (
            patch.object(vercel, "make_tracked_session", lambda *a, **k: session),
            patch.object(vercel, "capture_exception") as capture,
        ):
            ok, error = validate_credentials("token")

        assert ok is False
        assert error is not None
        assert "Vercel API error" not in error
        assert "418" not in error
        # The status has to reach error tracking, or a later triage has only the generic message.
        assert "418" in str(capture.call_args.args[0])


def _status_response(status_code: int, body: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.text = f"{status_code} body"
    response.json.return_value = body or {}
    if not response.ok:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Client Error", response=response)
    return response


class TestFetchPageRetry:
    @pytest.fixture(autouse=True)
    def _instant_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cast(Any, vercel._fetch_page).retry, "wait", wait_none())

    def test_408_is_retried_then_succeeds(self) -> None:
        session = MagicMock()
        session.get.side_effect = [_status_response(408), _status_response(200, {"deployments": []})]

        result = vercel._fetch_page(session, "https://api.vercel.com/v6/deployments", {}, MagicMock())

        assert result == {"deployments": []}
        assert session.get.call_count == 2

    def test_persistent_408_exhausts_retries(self) -> None:
        session = MagicMock()
        session.get.side_effect = [_status_response(408) for _ in range(5)]

        with pytest.raises(vercel.VercelRetryableError):
            vercel._fetch_page(session, "https://api.vercel.com/v6/deployments", {}, MagicMock())

    def test_400_is_not_retried(self) -> None:
        session = MagicMock()
        session.get.return_value = _status_response(400)

        with pytest.raises(requests.HTTPError):
            vercel._fetch_page(session, "https://api.vercel.com/v6/deployments", {}, MagicMock())
        assert session.get.call_count == 1


class TestOpenBillingStreamRetry:
    @pytest.fixture(autouse=True)
    def _instant_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cast(Any, vercel._open_billing_stream).retry, "wait", wait_none())

    def test_408_is_retried_then_succeeds(self) -> None:
        session = MagicMock()
        timeout_response = _status_response(408)
        ok_response = _status_response(200)
        session.get.side_effect = [timeout_response, ok_response]

        result = vercel._open_billing_stream(session, "https://api.vercel.com/v1/billing/charges", {}, MagicMock())

        assert result is ok_response
        assert session.get.call_count == 2
        timeout_response.close.assert_called_once()


class TestGetRows:
    def test_resumes_from_saved_until_cursor(self, monkeypatch: Any) -> None:
        responses = [{"deployments": [{"uid": "1", "created": 400}], "pagination": {"next": None}}]
        manager = _FakeResumableManager(VercelResumeConfig(until=500))
        rows, calls = _collect("deployments", manager, monkeypatch, responses)

        assert [r["uid"] for r in rows] == ["1"]
        assert "until=500" in calls[0]

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


class TestBillingWindowStart:
    def test_incremental_reads_from_the_day_floored_watermark(self) -> None:
        now = datetime(2026, 6, 15, 9, 30, tzinfo=UTC)
        watermark = datetime(2026, 6, 10, 14, 45, tzinfo=UTC)
        start = _billing_window_start(
            should_use_incremental_field=True, db_incremental_field_last_value=watermark, now=now
        )
        assert start == datetime(2026, 6, 10, tzinfo=UTC)


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
