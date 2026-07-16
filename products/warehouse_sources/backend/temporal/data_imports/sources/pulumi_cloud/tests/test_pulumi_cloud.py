from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud import pulumi_cloud
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.pulumi_cloud import (
    AUDIT_LOGS_LOOKBACK_SECONDS,
    PAGE_SIZE,
    STACK_UPDATES_LOOKBACK_SECONDS,
    PulumiCloudResumeConfig,
    _as_unix_seconds,
    _flatten_update,
    get_rows,
    pulumi_cloud_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.settings import (
    PULUMI_CLOUD_ENDPOINTS,
)


class _FakeResumableManager:
    def __init__(self, state: PulumiCloudResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PulumiCloudResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PulumiCloudResumeConfig | None:
        return self._state

    def save_state(self, data: PulumiCloudResumeConfig) -> None:
        self.saved.append(data)


def _run_rows(
    endpoint: str,
    fake_fetch: Any,
    manager: _FakeResumableManager,
    **incremental: Any,
) -> list[dict]:
    rows: list[dict] = []
    with patch.object(pulumi_cloud, "_fetch", fake_fetch):
        for page in get_rows(
            access_token="pul-test",
            organization="my-org",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **incremental,
        ):
            rows.extend(page)
    return rows


def _stack_summary(project: str, stack: str) -> dict[str, Any]:
    return {"id": f"my-org/{project}/{stack}", "orgName": "my-org", "projectName": project, "stackName": stack}


class TestAsUnixSeconds:
    @parameterized.expand(
        [
            ("int", 1750000000, 1750000000),
            ("float", 1750000000.7, 1750000000),
            ("numeric_string", "1750000000", 1750000000),
            ("datetime", datetime(2026, 6, 15, tzinfo=UTC), 1781481600),
            ("bool", True, None),
            ("garbage_string", "not-a-timestamp", None),
            ("none", None, None),
        ]
    )
    def test_coercion(self, _name: str, value: Any, expected: int | None) -> None:
        # A miscoerced watermark would either crash the sync or silently disable the incremental
        # bound and re-pull full history every run.
        assert _as_unix_seconds(value) == expected


class TestStacks:
    def test_pagination_follows_continuation_token_and_saves_state_after_yield(self) -> None:
        pages = {
            None: {"stacks": [_stack_summary("proj", "dev")], "continuationToken": "tok-2"},
            "tok-2": {"stacks": [_stack_summary("proj", "prod")]},
        }
        seen_tokens: list[str | None] = []

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            token = (params or {}).get("continuationToken")
            seen_tokens.append(token)
            return pages[token]

        manager = _FakeResumableManager()
        rows = _run_rows("stacks", fake_fetch, manager)

        assert seen_tokens == [None, "tok-2"]
        assert [r["stackName"] for r in rows] == ["dev", "prod"]
        # State is saved after yielding a page, and only while more pages remain — so a crash
        # re-yields the last page (merge dedupes) instead of skipping it.
        assert [s.next_token for s in manager.saved] == ["tok-2"]

    def test_resume_starts_from_saved_token(self) -> None:
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            assert (params or {}).get("continuationToken") == "tok-2"
            return {"stacks": [_stack_summary("proj", "prod")]}

        manager = _FakeResumableManager(PulumiCloudResumeConfig(next_token="tok-2"))
        rows = _run_rows("stacks", fake_fetch, manager)
        assert [r["stackName"] for r in rows] == ["prod"]


class TestFlattenUpdate:
    def test_flattens_info_injects_stack_coordinates_and_drops_deployment(self) -> None:
        # The nested `info` carries the analytics payload (kind/result/times); the raw deployment
        # state snapshot can be enormous and must not reach the warehouse row. The injected stack
        # coordinates are what make the composite primary key unique table-wide.
        item = {
            "updateID": "u-1",
            "version": 3,
            "latestVersion": 5,
            "requestedBy": {"githubLogin": "alice"},
            "info": {
                "kind": "update",
                "startTime": 1750000000,
                "endTime": 1750000060,
                "result": "succeeded",
                "resourceChanges": {"create": 2},
                "deployment": {"huge": "snapshot"},
            },
        }
        row = _flatten_update(item, "my-org", "proj", "dev")
        assert row == {
            "updateID": "u-1",
            "version": 3,
            "latestVersion": 5,
            "requestedBy": {"githubLogin": "alice"},
            "kind": "update",
            "startTime": 1750000000,
            "endTime": 1750000060,
            "result": "succeeded",
            "resourceChanges": {"create": 2},
            "orgName": "my-org",
            "projectName": "proj",
            "stackName": "dev",
        }

    def test_item_without_info_still_gets_stack_coordinates(self) -> None:
        row = _flatten_update({"updateID": "u-2", "version": 1}, "my-org", "proj", "dev")
        assert row["projectName"] == "proj"
        assert row["version"] == 1


class TestStackUpdates:
    def _make_pages(self, start_times_per_page: list[list[int]]) -> Any:
        stack_list = {"stacks": [_stack_summary("proj", "dev")]}

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            if url.endswith("/api/user/stacks"):
                return stack_list
            page = (params or {}).get("page", 1)
            if page > len(start_times_per_page):
                return {"updates": []}
            return {
                "updates": [
                    {"updateID": f"u-{t}", "version": t, "info": {"startTime": t}}
                    for t in start_times_per_page[page - 1]
                ]
            }

        return fake_fetch

    def test_full_refresh_walks_pages_until_short_page(self) -> None:
        pages = [list(range(2 * PAGE_SIZE, PAGE_SIZE, -1)), list(range(PAGE_SIZE, PAGE_SIZE - 30, -1))]
        rows = _run_rows("stack_updates", self._make_pages(pages), _FakeResumableManager())
        assert len(rows) == PAGE_SIZE + 30
        assert rows[0]["orgName"] == "my-org"

    def test_incremental_stops_once_a_page_predates_the_watermark(self) -> None:
        # Updates arrive newest-first with no server-side time filter; without the client-side stop
        # every incremental sync would re-walk each stack's full history (API-cost bug and memory
        # amplifier). Rows below the effective watermark must also not be re-yielded.
        effective_watermark = 2000
        raw_watermark = effective_watermark + STACK_UPDATES_LOOKBACK_SECONDS
        first_page = list(range(2050, 2050 - PAGE_SIZE, -1))  # full page reaching below 2000
        second_page = list(range(1950, 1850, -1))  # must never be fetched

        fetched_pages: list[int] = []
        inner = self._make_pages([first_page, second_page])

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            if not url.endswith("/api/user/stacks"):
                fetched_pages.append((params or {}).get("page", 1))
            return inner(session, url, headers, logger, params)

        rows = _run_rows(
            "stack_updates",
            fake_fetch,
            _FakeResumableManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=raw_watermark,
            incremental_field="startTime",
        )

        assert fetched_pages == [1]
        assert [r["startTime"] for r in rows] == list(range(2050, effective_watermark - 1, -1))

    def test_incremental_without_watermark_walks_full_history(self) -> None:
        pages = [list(range(2 * PAGE_SIZE, PAGE_SIZE, -1)), [50]]
        rows = _run_rows(
            "stack_updates",
            self._make_pages(pages),
            _FakeResumableManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="startTime",
        )
        assert len(rows) == PAGE_SIZE + 1

    def test_fan_out_marks_stacks_completed_and_resume_skips_them(self) -> None:
        stacks = [_stack_summary("proj", "dev"), _stack_summary("proj", "prod")]

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            if url.endswith("/api/user/stacks"):
                return {"stacks": stacks}
            stack = url.split("/updates")[0].rsplit("/", 1)[-1]
            return {"updates": [{"updateID": f"u-{stack}", "version": 1, "info": {"startTime": 1}}]}

        manager = _FakeResumableManager()
        _run_rows("stack_updates", fake_fetch, manager)
        # Completed keys accumulate AFTER each stack's rows are yielded, so a crash mid-stack
        # re-processes that stack (merge dedupes) rather than skipping it.
        assert [s.completed_stack_keys for s in manager.saved] == [
            ["my-org/proj/dev"],
            ["my-org/proj/dev", "my-org/proj/prod"],
        ]

        resumed = _FakeResumableManager(PulumiCloudResumeConfig(completed_stack_keys=["my-org/proj/dev"]))
        rows = _run_rows("stack_updates", fake_fetch, resumed)
        assert [r["stackName"] for r in rows] == ["prod"]


class TestDeployments:
    def test_paginates_until_short_page_and_saves_next_page_after_yield(self) -> None:
        pages = {
            1: {"deployments": [{"id": f"d{i}", "created": "2026-06-01T00:00:00Z"} for i in range(PAGE_SIZE)]},
            2: {"deployments": [{"id": "last", "created": "2026-05-01T00:00:00Z"}]},
        }
        seen_pages: list[int] = []

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            page = (params or {}).get("page", 1)
            seen_pages.append(page)
            return pages[page]

        manager = _FakeResumableManager()
        rows = _run_rows("deployments", fake_fetch, manager)

        assert seen_pages == [1, 2]
        assert len(rows) == PAGE_SIZE + 1
        # Saved AFTER yielding page 1: a crash between yield and save re-fetches page 1 (merge
        # dedupes) instead of skipping it.
        assert [s.page for s in manager.saved] == [2]

    def test_resume_starts_from_saved_page(self) -> None:
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            assert (params or {}).get("page") == 3
            return {"deployments": [{"id": "d-resumed"}]}

        manager = _FakeResumableManager(PulumiCloudResumeConfig(page=3))
        rows = _run_rows("deployments", fake_fetch, manager)
        assert [r["id"] for r in rows] == ["d-resumed"]

    def test_empty_first_page_yields_nothing(self) -> None:
        # Orgs without Pulumi Deployments get an empty listing, not an error.
        rows = _run_rows("deployments", lambda *a, **k: {"deployments": []}, _FakeResumableManager())
        assert rows == []


class TestAuditLogs:
    def _pages_fetch(self, captured: list[dict]) -> Any:
        pages = {
            None: {"auditLogEvents": [{"timestamp": 100, "event": "stack.update"}], "continuationToken": "c-2"},
            "c-2": {"auditLogEvents": [{"timestamp": 90, "event": "member.added"}]},
        }

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            captured.append(dict(params or {}))
            return pages[(params or {}).get("continuationToken")]

        return fake_fetch

    def test_incremental_passes_server_side_start_time_lower_bound(self) -> None:
        # The v2 endpoint's startTime is the genuine server-side filter this table's incremental
        # support is built on; dropping it would re-pull the org's entire audit history every run.
        captured: list[dict] = []
        manager = _FakeResumableManager()
        rows = _run_rows(
            "audit_logs",
            self._pages_fetch(captured),
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1750000000,
            incremental_field="timestamp",
        )

        expected_start = 1750000000 - AUDIT_LOGS_LOOKBACK_SECONDS
        assert all(p.get("startTime") == expected_start for p in captured)
        assert captured[1]["continuationToken"] == "c-2"
        assert [r["timestamp"] for r in rows] == [100, 90]
        assert [s.next_token for s in manager.saved] == ["c-2"]

    def test_full_refresh_omits_start_time(self) -> None:
        captured: list[dict] = []
        _run_rows("audit_logs", self._pages_fetch(captured), _FakeResumableManager())
        assert all("startTime" not in p for p in captured)

    def test_synthetic_event_id_distinguishes_events_colliding_on_time_type_description(self) -> None:
        # Two distinct events sharing timestamp/type/description but differing only by actor must not
        # collapse onto one primary key; an identical re-pulled event must reuse its key so it dedupes.
        page = {
            "auditLogEvents": [
                {"timestamp": 100, "event": "stack.update", "description": "updated prod", "user": "alice"},
                {"timestamp": 100, "event": "stack.update", "description": "updated prod", "user": "bob"},
                {"timestamp": 100, "event": "stack.update", "description": "updated prod", "user": "alice"},
            ]
        }
        rows = _run_rows("audit_logs", lambda *a, **k: page, _FakeResumableManager())

        assert PULUMI_CLOUD_ENDPOINTS["audit_logs"].primary_keys == ["event_id"]
        assert rows[0]["event_id"] != rows[1]["event_id"]
        assert rows[0]["event_id"] == rows[2]["event_id"]


class TestResources:
    def test_cursor_advances_only_while_next_link_present(self) -> None:
        # The final page can still echo a cursor back; only the `next` link signals another page.
        # Following the echoed cursor would loop on the last page forever.
        pages = {
            None: {
                "resources": [{"urn": "urn:1", "project": "p", "stack": "s"}],
                "pagination": {"cursor": "cur-2", "next": "https://api.pulumi.com/next"},
            },
            "cur-2": {
                "resources": [{"urn": "urn:2", "project": "p", "stack": "s"}],
                "pagination": {"cursor": "cur-2"},
            },
        }
        seen_cursors: list[str | None] = []

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            cursor = (params or {}).get("cursor")
            seen_cursors.append(cursor)
            return pages[cursor]

        manager = _FakeResumableManager()
        rows = _run_rows("resources", fake_fetch, manager)

        assert seen_cursors == [None, "cur-2"]
        assert [r["urn"] for r in rows] == ["urn:1", "urn:2"]
        assert [s.next_token for s in manager.saved] == ["cur-2"]

    def test_empty_page_terminates(self) -> None:
        rows = _run_rows("resources", lambda *a, **k: {"resources": []}, _FakeResumableManager())
        assert rows == []


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(pulumi_cloud, "make_tracked_session", return_value=session):
            assert validate_credentials("pul-test") is expected

    def test_network_error_is_not_valid(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch.object(pulumi_cloud, "make_tracked_session", return_value=session):
            assert validate_credentials("pul-test") is False


class TestFetchRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_are_retried(self, _name: str, status: int) -> None:
        bad = MagicMock(status_code=status)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"ok": True}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(pulumi_cloud._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = pulumi_cloud._fetch(session, "https://api.pulumi.com/api/user", {}, MagicMock())

        assert result == {"ok": True}
        assert session.get.call_count == 2

    def test_client_error_raises_without_retry(self) -> None:
        import requests

        bad = requests.Response()
        bad.status_code = 401
        session = MagicMock()
        session.get.return_value = bad

        with pytest.raises(requests.HTTPError):
            pulumi_cloud._fetch(session, "https://api.pulumi.com/api/user", {}, MagicMock())
        assert session.get.call_count == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            ("stacks", "asc", None),
            # Newest-first endpoints report "desc" so the incremental watermark persists only at
            # successful job end; "asc" per-batch persistence would checkpoint the watermark to
            # ≈now after the first (newest) batch and lose everything a crashed run still owed.
            ("stack_updates", "desc", None),
            ("deployments", "desc", "created"),
            ("audit_logs", "desc", None),
            ("resources", "asc", "created"),
        ]
    )
    def test_sort_mode_partition_and_primary_keys(
        self, endpoint: str, expected_sort: str, partition_key: str | None
    ) -> None:
        response = pulumi_cloud_source(
            access_token="pul-test",
            organization="my-org",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.sort_mode == expected_sort
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.primary_keys == PULUMI_CLOUD_ENDPOINTS[endpoint].primary_keys
