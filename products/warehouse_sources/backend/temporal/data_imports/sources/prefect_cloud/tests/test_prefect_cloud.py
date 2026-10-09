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
    def test_incremental_unknown_field_falls_back_to_first_advertised(self) -> None:
        body = _build_json_body(
            PREFECT_CLOUD_ENDPOINTS["flow_runs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="updated",
        )
        assert body["flow_runs"] == {"start_time": {"after_": "2026-03-04T00:00:00Z"}}
        assert body["sort"] == "START_TIME_ASC"

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # flows has no server-side time filter; a cursor must not leak into the request.
        body = _build_json_body(
            PREFECT_CLOUD_ENDPOINTS["flows"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="created",
        )
        assert body == {"sort": "CREATED_ASC"}


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
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([{"id": "resumed"}])])

        manager = _make_manager(PrefectCloudResumeConfig(offset=PAGE_LIMIT))
        rows = _rows(_source(manager, endpoint="flows"))

        assert [r["id"] for r in rows] == ["resumed"]
        assert [b["offset"] for b in bodies] == [PAGE_LIMIT]

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
