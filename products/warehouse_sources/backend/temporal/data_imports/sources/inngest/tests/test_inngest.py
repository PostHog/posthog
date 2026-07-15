import json
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.inngest import inngest
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.inngest import (
    EVENTS_PAGE_SIZE,
    InngestResumeConfig,
    _event_window,
    get_rows,
    inngest_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.settings import INNGEST_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: InngestResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[InngestResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> InngestResumeConfig | None:
        return self._state

    def save_state(self, data: InngestResumeConfig) -> None:
        self.saved.append(data)


def _event(internal_id: str, received_at: str = "2026-07-10T10:00:00.000Z", **extra: Any) -> dict[str, Any]:
    return {"internal_id": internal_id, "receivedAt": received_at, "name": "app/user.signed.up", **extra}


def _run_rows(
    endpoint: str,
    fake_fetch: Any,
    manager: _FakeResumableManager | None = None,
    **incremental: Any,
) -> tuple[list[dict], _FakeResumableManager]:
    manager = manager or _FakeResumableManager()
    rows: list[dict] = []
    with patch.object(inngest, "_fetch", fake_fetch), patch.object(inngest, "make_tracked_session", MagicMock()):
        for batch in get_rows(
            signing_key="signkey-prod-test",
            environment=None,
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **incremental,
        ):
            rows.extend(batch)
    return rows, manager


class TestEventWindow:
    @freeze_time("2026-07-14T12:00:00Z")
    def test_first_sync_backfills_the_max_retention_window(self) -> None:
        # received_after defaults to only 1 hour ago server-side, so leaving it off a first sync
        # would silently drop everything older than an hour.
        after, before = _event_window(should_use_incremental_field=False, db_incremental_field_last_value=None)
        assert after == "2026-04-15T12:00:00.000Z"
        assert before == "2026-07-14T12:00:00.000Z"

    @parameterized.expand(
        [
            ("iso_string", "2026-07-10T08:30:00+00:00", "2026-07-10T08:30:00.000Z"),
            ("iso_string_z", "2026-07-10T08:30:00.500Z", "2026-07-10T08:30:00.500Z"),
        ]
    )
    @freeze_time("2026-07-14T12:00:00Z")
    def test_incremental_run_advances_from_the_watermark(self, _name: str, value: Any, expected_after: str) -> None:
        after, _ = _event_window(should_use_incremental_field=True, db_incremental_field_last_value=value)
        assert after == expected_after

    @freeze_time("2026-07-14T12:00:00Z")
    def test_future_watermark_is_clamped_to_now(self) -> None:
        # A future-dated watermark would produce an inverted window that returns nothing forever.
        after, before = _event_window(
            should_use_incremental_field=True, db_incremental_field_last_value="2027-01-01T00:00:00Z"
        )
        assert after == before == "2026-07-14T12:00:00.000Z"


class TestEventsPagination:
    def test_paginates_with_cursor_and_pinned_window(self) -> None:
        # Every page must carry the explicit received_after/received_before window (the server
        # default is 1 hour) plus the cursor from the previous page's last event.
        pages = [
            [_event(f"01A{i:03d}") for i in range(EVENTS_PAGE_SIZE)],
            [_event("01B000"), _event("01B001")],
        ]
        seen_params: list[dict] = []

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            seen_params.append(dict(params or {}))
            return {"data": pages[len(seen_params) - 1]}

        rows, _ = _run_rows("events", fake_fetch)

        assert len(rows) == EVENTS_PAGE_SIZE + 2
        assert "cursor" not in seen_params[0]
        assert seen_params[1]["cursor"] == "01A099"
        for params in seen_params:
            assert params["limit"] == EVENTS_PAGE_SIZE
            assert params["received_after"]
            assert params["received_before"]
        # The window must not shift between pages while new events keep arriving.
        assert seen_params[0]["received_before"] == seen_params[1]["received_before"]

    @parameterized.expand(
        [
            ("empty_first_page", [[]], 0),
            ("partial_page_stops", [[_event("01A000")]], 1),
        ]
    )
    def test_pagination_terminates(self, _name: str, pages: list[list[dict]], expected_rows: int) -> None:
        calls: list[int] = []

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            calls.append(1)
            return {"data": pages[len(calls) - 1]}

        rows, _ = _run_rows("events", fake_fetch)
        assert len(rows) == expected_rows
        assert len(calls) == 1

    def test_state_saved_after_each_full_page_but_not_the_final_page(self) -> None:
        # Saving before the yield would skip the last page on crash; saving on the final page would
        # make a retry resume into an exhausted walk.
        pages = [
            [_event(f"01A{i:03d}") for i in range(EVENTS_PAGE_SIZE)],
            [_event("01B000")],
        ]
        calls: list[int] = []

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            calls.append(1)
            return {"data": pages[len(calls) - 1]}

        _, manager = _run_rows("events", fake_fetch)
        assert [s.cursor for s in manager.saved] == ["01A099"]
        assert manager.saved[0].received_after and manager.saved[0].received_before

    def test_resume_continues_the_saved_walk(self) -> None:
        # A resumed attempt must reuse the saved cursor and pinned window, not re-derive a new
        # window from the clock (which would re-fetch everything already yielded).
        state = InngestResumeConfig(
            cursor="01A099",
            received_after="2026-07-01T00:00:00.000Z",
            received_before="2026-07-14T00:00:00.000Z",
        )
        seen_params: list[dict] = []

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            seen_params.append(dict(params or {}))
            return {"data": [_event("01B000")]}

        _run_rows("events", fake_fetch, manager=_FakeResumableManager(state))
        assert seen_params[0]["cursor"] == "01A099"
        assert seen_params[0]["received_after"] == "2026-07-01T00:00:00.000Z"
        assert seen_params[0]["received_before"] == "2026-07-14T00:00:00.000Z"

    def test_cursor_event_returned_again_is_dropped(self) -> None:
        # We couldn't verify whether the API's cursor is inclusive; re-yielding the cursor event
        # would duplicate it in append mode, so it must be filtered out.
        pages = [
            [_event(f"01A{i:03d}") for i in range(EVENTS_PAGE_SIZE)],
            [_event("01A099"), _event("01B000")],
        ]
        calls: list[int] = []

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            calls.append(1)
            return {"data": pages[len(calls) - 1]}

        rows, _ = _run_rows("events", fake_fetch)
        assert [r["internal_id"] for r in rows].count("01A099") == 1

    @parameterized.expand(
        [
            ("camel_case", {"internal_id": "01A000", "receivedAt": "2026-07-10T10:00:00.000Z"}),
            ("snake_case", {"internal_id": "01A000", "received_at": "2026-07-10T10:00:00.000Z"}),
        ]
    )
    def test_received_at_is_normalized_from_either_spelling(self, _name: str, item: dict) -> None:
        # The v1 spec documents `receivedAt` amid snake_case fields and the live casing is
        # unverified; the incremental/partition column must exist under one stable name either way.
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            return {"data": [dict(item)]}

        rows, _ = _run_rows("events", fake_fetch)
        assert rows[0]["received_at"] == "2026-07-10T10:00:00.000Z"
        assert "receivedAt" not in rows[0]


class TestFunctionRunsFanOut:
    def test_fetches_runs_per_event_and_injects_event_received_at(self) -> None:
        runs_by_event = {
            "01A000": [{"run_id": "r1", "status": "Completed", "output": {"ok": True}}],
            "01A001": [],
        }

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            if url.endswith("/runs"):
                internal_id = url.rsplit("/", 2)[-2]
                return {"data": runs_by_event[internal_id]}
            return {"data": [_event("01A000"), _event("01A001")]}

        rows, _ = _run_rows("function_runs", fake_fetch)
        assert len(rows) == 1
        # The parent event's received time drives the incremental watermark; a run's own
        # timestamps can lag behind (debounce) and would advance the watermark past unseen events.
        assert rows[0]["event_received_at"] == "2026-07-10T10:00:00.000Z"
        # Non-string outputs are JSON-encoded so the column keeps one stable type across rows.
        assert rows[0]["output"] == json.dumps({"ok": True})

    def test_batch_run_returned_for_every_event_is_deduped(self) -> None:
        # A batch run appears under every event in its batch; duplicate run_id rows within one
        # sync seed the Delta table with dupes that every later merge multi-matches.
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            if url.endswith("/runs"):
                return {"data": [{"run_id": "r-batch", "status": "Completed", "output": None}]}
            return {"data": [_event("01A000"), _event("01A001")]}

        rows, _ = _run_rows("function_runs", fake_fetch)
        assert [r["run_id"] for r in rows] == ["r-batch"]


class TestV2ListPagination:
    def test_follows_page_cursor_until_has_more_is_false(self) -> None:
        pages = [
            {"data": [{"id": "env-1"}], "page": {"cursor": "c2", "hasMore": True}},
            {"data": [{"id": "env-2"}], "page": {"cursor": "c3", "hasMore": False}},
        ]
        seen_params: list[dict | None] = []

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            seen_params.append(params)
            return pages[len(seen_params) - 1]

        rows, _ = _run_rows("environments", fake_fetch)
        assert [r["id"] for r in rows] == ["env-1", "env-2"]
        assert seen_params == [None, {"cursor": "c2"}]

    def test_repeated_cursor_breaks_the_loop(self) -> None:
        # A server bug returning hasMore=True with the same cursor forever must not loop the sync.
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            return {"data": [{"id": "env-1"}], "page": {"cursor": "same", "hasMore": True}}

        rows, _ = _run_rows("environments", fake_fetch)
        assert len(rows) == 2  # first page + the one repeat before the guard trips

    @parameterized.expand([("event_keys",), ("signing_keys",)])
    def test_secret_key_material_is_never_synced(self, endpoint: str) -> None:
        # The v2 key inventories return the raw `key` secret; syncing it would copy live
        # credentials into the warehouse.
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            return {
                "data": [{"id": "k1", "name": "prod key", "key": "signkey-prod-secretvalue"}],
                "page": {"hasMore": False},
            }

        rows, _ = _run_rows(endpoint, fake_fetch)
        assert rows == [{"id": "k1", "name": "prod key"}]


class TestV1Lists:
    @parameterized.expand(
        [
            ("list_payload", {"data": [{"id": "c1"}, {"id": "c2"}]}, ["c1", "c2"]),
            # The v1 spec is ambiguous about single-object vs array envelopes for these lists.
            ("single_object_payload", {"data": {"id": "c1"}}, ["c1"]),
            ("empty", {"data": []}, []),
        ]
    )
    def test_cancellations_handle_list_and_object_envelopes(
        self, _name: str, payload: dict, expected_ids: list[str]
    ) -> None:
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            return payload

        rows, _ = _run_rows("cancellations", fake_fetch)
        assert [r["id"] for r in rows] == expected_ids

    def test_webhook_intake_url_is_never_synced(self) -> None:
        # The intake URL is capability-bearing: anyone holding it can submit events that trigger
        # Inngest functions, so it must not be copied into a warehouse table viewers can read.
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            return {"data": [{"id": "wh1", "name": "github intake", "url": "https://inn.gs/e/secret-intake-token"}]}

        rows, _ = _run_rows("webhooks", fake_fetch)
        assert rows == [{"id": "wh1", "name": "github intake"}]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(inngest, "make_tracked_session", return_value=session):
            assert validate_credentials("signkey-prod-test") is expected

    def test_environment_header_is_sent_when_configured(self) -> None:
        # A branch environment's data is only reachable with the X-Inngest-Env header; dropping it
        # would validate (and later sync) the production environment instead.
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response
        with patch.object(inngest, "make_tracked_session", return_value=session):
            validate_credentials("signkey-branch-test", "my-branch")
        assert session.get.call_args.kwargs["headers"]["X-Inngest-Env"] == "my-branch"

    def test_network_error_is_not_valid(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch.object(inngest, "make_tracked_session", return_value=session):
            assert validate_credentials("signkey-prod-test") is False


class TestFetchRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_are_retried(self, _name: str, status: int) -> None:
        bad = MagicMock(status_code=status)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"ok": True}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(inngest._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = inngest._fetch(session, "https://api.inngest.com/v1/events", {}, MagicMock())

        assert result == {"ok": True}
        assert session.get.call_count == 2

    def test_client_error_raises_without_retry(self) -> None:
        import requests

        bad = requests.Response()
        bad.status_code = 401
        session = MagicMock()
        session.get.return_value = bad

        with pytest.raises(requests.HTTPError):
            inngest._fetch(session, "https://api.inngest.com/v1/events", {}, MagicMock())
        assert session.get.call_count == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            # The event-walk endpoints must report "desc" so the watermark is persisted only at
            # successful job end — the walk's arrival order within the window is unverified.
            ("events", "desc", "received_at"),
            ("function_runs", "desc", "run_started_at"),
            ("cancellations", "asc", None),
            ("environments", "asc", None),
            ("webhooks", "asc", None),
            ("event_keys", "asc", None),
            ("signing_keys", "asc", None),
        ]
    )
    def test_sort_mode_partition_and_primary_keys(
        self, endpoint: str, expected_sort: str, partition_key: str | None
    ) -> None:
        response = inngest_source(
            signing_key="signkey-prod-test",
            environment=None,
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.sort_mode == expected_sort
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.primary_keys == INNGEST_ENDPOINTS[endpoint].primary_keys
