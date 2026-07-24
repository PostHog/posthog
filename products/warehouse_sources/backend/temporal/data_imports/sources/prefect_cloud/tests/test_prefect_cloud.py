import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud import prefect_cloud
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.prefect_cloud import (
    PrefectCloudResumeConfig,
    _build_json_body,
    _format_after,
    normalize_uuid,
    prefect_cloud_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.settings import (
    PAGE_LIMIT,
    PREFECT_CLOUD_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the prefect_cloud module.
PREFECT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.prefect_cloud.make_tracked_session"
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


class TestBuildJsonBody:
    # The static body carries the nested filter + sort; the paginator injects limit/offset per page.
    def test_incremental_adds_nested_filter_and_ascending_sort(self) -> None:
        body = _build_json_body(
            PREFECT_CLOUD_ENDPOINTS["flow_runs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="start_time",
        )
        assert body == {
            "flow_runs": {"start_time": {"after_": "2026-03-04T02:58:14Z"}},
            "sort": "START_TIME_ASC",
        }

    def test_incremental_honors_users_chosen_cursor_field(self) -> None:
        body = _build_json_body(
            PREFECT_CLOUD_ENDPOINTS["flow_runs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="expected_start_time",
        )
        assert body["flow_runs"] == {"expected_start_time": {"after_": "2026-03-04T00:00:00Z"}}
        assert body["sort"] == "EXPECTED_START_TIME_ASC"

    def test_incremental_unknown_field_falls_back_to_first_advertised(self) -> None:
        body = _build_json_body(
            PREFECT_CLOUD_ENDPOINTS["flow_runs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="updated",
        )
        assert body["flow_runs"] == {"start_time": {"after_": "2026-03-04T00:00:00Z"}}
        assert body["sort"] == "START_TIME_ASC"

    def test_incremental_without_cursor_omits_filter(self) -> None:
        body = _build_json_body(
            PREFECT_CLOUD_ENDPOINTS["flow_runs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="start_time",
        )
        assert body == {"sort": "EXPECTED_START_TIME_ASC"}

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # flows has no server-side time filter; a cursor must not leak into the request.
        body = _build_json_body(
            PREFECT_CLOUD_ENDPOINTS["flows"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="created",
        )
        assert body == {"sort": "CREATED_ASC"}

    def test_work_queues_body_has_no_sort(self) -> None:
        # The work_queues filter endpoint rejects unknown body keys, and its model has no `sort`.
        body = _build_json_body(
            PREFECT_CLOUD_ENDPOINTS["work_queues"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert body == {}


def _response(items: list[dict[str, Any]]) -> Response:
    # Prefect's filter endpoints return a bare JSON array of rows.
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(items).encode()
    return resp


def _make_manager(resume_state: PrefectCloudResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's JSON body AT SEND TIME.

    The paginator mutates ``request.json`` in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    body_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        body_snapshots.append(dict(request.json or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return body_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, **kwargs: Any):
    return prefect_cloud_source(
        account_id=_ACCOUNT_ID,
        workspace_id=_WORKSPACE_ID,
        api_key="pnu_key",
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": str(n)} for n in range(PAGE_LIMIT)]
        bodies = _wire(session, [_response(full_page), _response([{"id": "last"}])])

        manager = _make_manager()
        rows = _rows(_source(manager, endpoint="flows"))

        assert len(rows) == PAGE_LIMIT + 1
        assert rows[-1]["id"] == "last"
        assert [b["offset"] for b in bodies] == [0, PAGE_LIMIT]
        assert all(b["limit"] == PAGE_LIMIT for b in bodies)
        # flows is full refresh with a stable creation-time sort.
        assert all(b["sort"] == "CREATED_ASC" for b in bodies)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_after_each_yielded_full_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": str(n)} for n in range(PAGE_LIMIT)]
        _wire(session, [_response(full_page), _response([{"id": "last"}])])

        manager = _make_manager()
        _rows(_source(manager, endpoint="flows"))

        # State is saved only while more pages remain (after the full page), never on the last page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == PrefectCloudResumeConfig(offset=PAGE_LIMIT)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a"}, {"id": "b"}])])

        manager = _make_manager()
        rows = _rows(_source(manager, endpoint="flows"))

        assert [r["id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([{"id": "resumed"}])])

        manager = _make_manager(PrefectCloudResumeConfig(offset=PAGE_LIMIT))
        rows = _rows(_source(manager, endpoint="flows"))

        assert [r["id"] for r in rows] == ["resumed"]
        assert [b["offset"] for b in bodies] == [PAGE_LIMIT]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source(manager, endpoint="flows"))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_rides_every_page(self, MockSession) -> None:
        # Prefect takes the filter in the POST body, so later pages must carry the same watermark.
        session = MockSession.return_value
        full_page = [{"id": str(n)} for n in range(PAGE_LIMIT)]
        bodies = _wire(session, [_response(full_page), _response([{"id": "last"}])])

        manager = _make_manager()
        _rows(
            _source(
                manager,
                endpoint="flow_runs",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="start_time",
            )
        )

        assert len(bodies) == 2
        assert all(b["flow_runs"] == {"start_time": {"after_": "2026-03-04T02:58:14Z"}} for b in bodies)
        assert all(b["sort"] == "START_TIME_ASC" for b in bodies)
        assert [b["offset"] for b in bodies] == [0, PAGE_LIMIT]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_targets_workspace_filter_path(self, MockSession) -> None:
        session = MockSession.return_value
        captured: list[str] = []

        def _prepare(request: Any) -> mock.MagicMock:
            captured.append(request.url)
            return mock.MagicMock()

        session.headers = {}
        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_response([{"id": "a"}])]

        _rows(_source(_make_manager(), endpoint="flows"))
        assert captured[0] == f"{_WORKSPACE_URL}/flows/filter"


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
        session = mock.MagicMock()
        session.post.return_value = mock.MagicMock(status_code=status_code)
        monkeypatch.setattr(prefect_cloud, "make_tracked_session", lambda *a, **k: session)

        assert validate_credentials(_ACCOUNT_ID, _WORKSPACE_ID, "pnu_key") == expected
        assert session.post.call_args.args[0] == f"{_WORKSPACE_URL}/flows/filter"

    def test_transport_error_returns_none_status(self, monkeypatch: Any) -> None:
        session = mock.MagicMock()
        session.post.side_effect = ConnectionError("boom")
        monkeypatch.setattr(prefect_cloud, "make_tracked_session", lambda *a, **k: session)

        assert validate_credentials(_ACCOUNT_ID, _WORKSPACE_ID, "pnu_key") == (False, None)

    def test_malformed_id_raises_before_any_request(self, monkeypatch: Any) -> None:
        session = mock.MagicMock()
        monkeypatch.setattr(prefect_cloud, "make_tracked_session", lambda *a, **k: session)

        with pytest.raises(ValueError):
            validate_credentials("not-a-uuid", _WORKSPACE_ID, "pnu_key")
        session.post.assert_not_called()
