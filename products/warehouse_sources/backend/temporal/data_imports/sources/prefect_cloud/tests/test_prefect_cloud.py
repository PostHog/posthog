from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud import prefect_cloud
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.prefect_cloud import (
    PrefectCloudResumeConfig,
    _build_request_body,
    _format_after,
    get_rows,
    normalize_uuid,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.settings import (
    PAGE_LIMIT,
    PREFECT_CLOUD_ENDPOINTS,
)

_ACCOUNT_ID = "11111111-2222-3333-4444-555555555555"
_WORKSPACE_ID = "66666666-7777-8888-9999-aaaaaaaaaaaa"
_WORKSPACE_URL = f"https://api.prefect.cloud/api/accounts/{_ACCOUNT_ID}/workspaces/{_WORKSPACE_ID}"


class TestNormalizeUuid:
    @parameterized.expand(
        [
            ("lowercase", _ACCOUNT_ID, _ACCOUNT_ID),
            ("uppercase", _ACCOUNT_ID.upper(), _ACCOUNT_ID),
            ("whitespace", f"  {_ACCOUNT_ID}  ", _ACCOUNT_ID),
        ]
    )
    def test_valid_uuids(self, _name: str, value: str, expected: str) -> None:
        assert normalize_uuid(value, "account ID") == expected

    @parameterized.expand(
        [
            ("path_injection", "1111/../other-account"),
            ("url", "https://app.prefect.cloud/account/11111111-2222-3333-4444-555555555555"),
            ("empty", ""),
            ("not_a_uuid", "my-workspace"),
        ]
    )
    def test_invalid_uuids_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_uuid(value, "account ID")


class TestFormatAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_after(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildRequestBody:
    def test_incremental_adds_nested_filter_and_ascending_sort(self) -> None:
        body = _build_request_body(
            PREFECT_CLOUD_ENDPOINTS["flow_runs"],
            offset=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="start_time",
        )
        assert body == {
            "limit": PAGE_LIMIT,
            "offset": 0,
            "flow_runs": {"start_time": {"after_": "2026-03-04T02:58:14Z"}},
            "sort": "START_TIME_ASC",
        }

    def test_incremental_honors_users_chosen_cursor_field(self) -> None:
        body = _build_request_body(
            PREFECT_CLOUD_ENDPOINTS["flow_runs"],
            offset=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="expected_start_time",
        )
        assert body["flow_runs"] == {"expected_start_time": {"after_": "2026-03-04T00:00:00Z"}}
        assert body["sort"] == "EXPECTED_START_TIME_ASC"

    def test_incremental_unknown_field_falls_back_to_first_advertised(self) -> None:
        body = _build_request_body(
            PREFECT_CLOUD_ENDPOINTS["flow_runs"],
            offset=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="updated",
        )
        assert body["flow_runs"] == {"start_time": {"after_": "2026-03-04T00:00:00Z"}}
        assert body["sort"] == "START_TIME_ASC"

    def test_incremental_without_cursor_omits_filter(self) -> None:
        body = _build_request_body(
            PREFECT_CLOUD_ENDPOINTS["flow_runs"],
            offset=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="start_time",
        )
        assert body == {"limit": PAGE_LIMIT, "offset": 0, "sort": "EXPECTED_START_TIME_ASC"}

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # flows has no server-side time filter; a cursor must not leak into the request.
        body = _build_request_body(
            PREFECT_CLOUD_ENDPOINTS["flows"],
            offset=200,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="created",
        )
        assert body == {"limit": PAGE_LIMIT, "offset": 200, "sort": "CREATED_ASC"}

    def test_work_queues_body_has_no_sort(self) -> None:
        # The work_queues filter endpoint rejects unknown body keys, and its model has no `sort`.
        body = _build_request_body(
            PREFECT_CLOUD_ENDPOINTS["work_queues"],
            offset=0,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert body == {"limit": PAGE_LIMIT, "offset": 0}


class _FakeResumableManager:
    def __init__(self, state: PrefectCloudResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PrefectCloudResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PrefectCloudResumeConfig | None:
        return self._state

    def save_state(self, data: PrefectCloudResumeConfig) -> None:
        self.saved.append(data)


def _patch_fetch(monkeypatch: Any, pages: dict[int, list[dict]]) -> list[dict]:
    """Serve pages keyed by the request body's offset, recording each body."""
    bodies: list[dict] = []

    def fake_fetch(session: Any, url: str, body: dict, headers: dict[str, str], logger: Any) -> list[dict]:
        bodies.append({"url": url, **body})
        return pages.get(body["offset"], [])

    monkeypatch.setattr(prefect_cloud, "_fetch_page", fake_fetch)
    return bodies


def _collect(manager: _FakeResumableManager, **kwargs: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in get_rows(
        account_id=_ACCOUNT_ID,
        workspace_id=_WORKSPACE_ID,
        api_key="pnu_key",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


class TestGetRows:
    def test_paginates_until_short_page(self, monkeypatch: Any) -> None:
        pages = {
            0: [{"id": str(n)} for n in range(PAGE_LIMIT)],
            PAGE_LIMIT: [{"id": "last"}],
        }
        bodies = _patch_fetch(monkeypatch, pages)
        rows = _collect(_FakeResumableManager(), endpoint="flows")

        assert len(rows) == PAGE_LIMIT + 1
        assert rows[-1]["id"] == "last"
        assert [b["offset"] for b in bodies] == [0, PAGE_LIMIT]
        assert all(b["url"] == f"{_WORKSPACE_URL}/flows/filter" for b in bodies)

    def test_saves_resume_state_after_each_yielded_full_page(self, monkeypatch: Any) -> None:
        pages = {
            0: [{"id": str(n)} for n in range(PAGE_LIMIT)],
            PAGE_LIMIT: [{"id": "last"}],
        }
        _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect(manager, endpoint="flows")

        # State is saved only while more pages remain (after the full page), never on the last page.
        assert manager.saved == [PrefectCloudResumeConfig(offset=PAGE_LIMIT)]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        pages = {PAGE_LIMIT: [{"id": "resumed"}]}
        bodies = _patch_fetch(monkeypatch, pages)
        rows = _collect(_FakeResumableManager(PrefectCloudResumeConfig(offset=PAGE_LIMIT)), endpoint="flows")

        assert [r["id"] for r in rows] == ["resumed"]
        assert [b["offset"] for b in bodies] == [PAGE_LIMIT]

    def test_stops_on_empty_first_page(self, monkeypatch: Any) -> None:
        bodies = _patch_fetch(monkeypatch, {0: []})
        rows = _collect(_FakeResumableManager(), endpoint="flows")

        assert rows == []
        assert len(bodies) == 1

    def test_incremental_filter_rides_every_page(self, monkeypatch: Any) -> None:
        # Prefect takes the filter in the POST body, so later pages must carry the same watermark.
        pages = {
            0: [{"id": str(n)} for n in range(PAGE_LIMIT)],
            PAGE_LIMIT: [{"id": "last"}],
        }
        bodies = _patch_fetch(monkeypatch, pages)
        _collect(
            _FakeResumableManager(),
            endpoint="flow_runs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="start_time",
        )

        assert all(b["flow_runs"] == {"start_time": {"after_": "2026-03-04T02:58:14Z"}} for b in bodies)
        assert all(b["sort"] == "START_TIME_ASC" for b in bodies)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, (True, 200)),
            (401, (False, 401)),
            (404, (False, 404)),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: tuple, monkeypatch: Any) -> None:
        session = MagicMock()
        session.post.return_value = MagicMock(status_code=status_code)
        monkeypatch.setattr(prefect_cloud, "make_tracked_session", lambda: session)

        assert validate_credentials(_ACCOUNT_ID, _WORKSPACE_ID, "pnu_key") == expected
        assert session.post.call_args.args[0] == f"{_WORKSPACE_URL}/flows/filter"

    def test_transport_error_returns_none_status(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.post.side_effect = ConnectionError("boom")
        monkeypatch.setattr(prefect_cloud, "make_tracked_session", lambda: session)

        assert validate_credentials(_ACCOUNT_ID, _WORKSPACE_ID, "pnu_key") == (False, None)

    def test_malformed_id_raises_before_any_request(self, monkeypatch: Any) -> None:
        session = MagicMock()
        monkeypatch.setattr(prefect_cloud, "make_tracked_session", lambda: session)

        with pytest.raises(ValueError):
            validate_credentials("not-a-uuid", _WORKSPACE_ID, "pnu_key")
        session.post.assert_not_called()
