import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.zero import (
    ZeroResumeConfig,
    _build_where,
    _format_zero_datetime,
    get_resource,
    resolve_workspace_id,
    validate_credentials,
    zero_source,
)

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"


def _make_http_response(body: dict[str, Any] | None, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body if body is not None else {}).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestFormatZeroDatetime:
    def test_naive_datetime_gets_utc_timezone(self) -> None:
        value = datetime(2026, 1, 1, 12, 0, 0)
        assert _format_zero_datetime(value) == "2026-01-01T12:00:00+00:00"

    def test_aware_datetime_is_converted_to_utc(self) -> None:
        from datetime import timedelta, timezone

        value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        assert _format_zero_datetime(value) == "2026-01-01T10:00:00+00:00"

    def test_date_is_combined_with_midnight_utc(self) -> None:
        assert _format_zero_datetime(date(2026, 1, 1)) == "2026-01-01T00:00:00+00:00"

    def test_string_value_passes_through(self) -> None:
        assert _format_zero_datetime("2026-01-01T00:00:00Z") == "2026-01-01T00:00:00Z"


class TestBuildWhere:
    def test_no_workspace_no_last_value_returns_empty_filter(self) -> None:
        convert = _build_where(None, "updatedAt")
        assert json.loads(convert(None)) == {}

    def test_workspace_only_when_no_last_value(self) -> None:
        convert = _build_where(WORKSPACE_ID, "updatedAt")
        assert json.loads(convert(None)) == {"workspaceId": WORKSPACE_ID}

    def test_workspace_and_date_filter_combined(self) -> None:
        convert = _build_where(WORKSPACE_ID, "updatedAt")
        result = json.loads(convert(datetime(2026, 1, 1, tzinfo=UTC)))
        assert result == {
            "workspaceId": WORKSPACE_ID,
            "updatedAt": {"$gt": "2026-01-01T00:00:00+00:00"},
        }

    def test_date_filter_without_workspace(self) -> None:
        # Users has no workspaceId field, so the filter must never include one.
        convert = _build_where(None, "updatedAt")
        result = json.loads(convert(datetime(2026, 1, 1, tzinfo=UTC)))
        assert result == {"updatedAt": {"$gt": "2026-01-01T00:00:00+00:00"}}

    def test_no_date_field_never_adds_a_date_filter(self) -> None:
        convert = _build_where(WORKSPACE_ID, None)
        result = json.loads(convert(datetime(2026, 1, 1, tzinfo=UTC)))
        assert result == {"workspaceId": WORKSPACE_ID}


class TestGetResource:
    @parameterized.expand(
        [
            ("Companies", "companies", "/api/companies"),
            ("Contacts", "contacts", "/api/contacts"),
            ("Deals", "deals", "/api/deals"),
            ("Pipelines", "pipelines", "/api/pipelines"),
            ("PipelineStages", "pipeline_stages", "/api/pipelineStages"),
            ("Notes", "notes", "/api/notes"),
            ("Tasks", "tasks", "/api/tasks"),
            ("Meetings", "meetings", "/api/calendarEvents"),
            ("Memberships", "memberships", "/api/memberships"),
            ("Workspaces", "workspaces", "/api/workspaces"),
            ("Users", "users", "/api/users"),
        ]
    )
    def test_endpoint_name_maps_to_table_and_path(self, endpoint: str, table_name: str, path: str) -> None:
        resource = get_resource(endpoint, WORKSPACE_ID, should_use_incremental_field=False, incremental_field=None)
        assert resource["table_name"] == table_name
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        assert endpoint_config["path"] == path
        assert resource["primary_key"] == ["id"]

    def test_full_refresh_scoped_endpoint_filters_by_workspace_only(self) -> None:
        resource = get_resource("Companies", WORKSPACE_ID, should_use_incremental_field=False, incremental_field=None)
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        params = endpoint_config["params"]
        assert isinstance(params, dict)
        where = params["where"]
        order_by = params["orderBy"]
        assert isinstance(where, str)
        assert isinstance(order_by, str)
        assert json.loads(where) == {"workspaceId": WORKSPACE_ID}
        assert json.loads(order_by) == {"createdAt": "asc"}
        assert resource["write_disposition"] == "replace"

    def test_full_refresh_users_endpoint_has_no_workspace_filter(self) -> None:
        resource = get_resource("Users", WORKSPACE_ID, should_use_incremental_field=False, incremental_field=None)
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        params = endpoint_config["params"]
        assert isinstance(params, dict)
        assert "where" not in params

    def test_incremental_uses_chosen_field_for_filter_and_sort(self) -> None:
        resource = get_resource(
            "Companies", WORKSPACE_ID, should_use_incremental_field=True, incremental_field="createdAt"
        )
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        params = endpoint_config["params"]
        assert isinstance(params, dict)
        where = params["where"]
        order_by = params["orderBy"]
        assert isinstance(where, dict)
        assert isinstance(order_by, str)
        assert where["cursor_path"] == "createdAt"  # ty: ignore[invalid-key]
        assert json.loads(order_by) == {"createdAt": "asc"}
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    def test_incremental_field_falls_back_to_first_advertised_option(self) -> None:
        resource = get_resource(
            "Companies", WORKSPACE_ID, should_use_incremental_field=True, incremental_field="not_a_real_field"
        )
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        params = endpoint_config["params"]
        assert isinstance(params, dict)
        where = params["where"]
        assert isinstance(where, dict)
        assert where["cursor_path"] == "updatedAt"  # ty: ignore[invalid-key]

    def test_incremental_convert_omits_workspace_for_users(self) -> None:
        resource = get_resource("Users", WORKSPACE_ID, should_use_incremental_field=True, incremental_field="updatedAt")
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        params = endpoint_config["params"]
        assert isinstance(params, dict)
        where = params["where"]
        assert isinstance(where, dict)
        convert = where["convert"]  # ty: ignore[invalid-key]
        assert convert is not None
        assert json.loads(convert(None)) == {}

    def test_workspaces_endpoint_never_goes_incremental(self) -> None:
        # Workspaces declares no incremental_fields, so should_use_incremental_field=True must
        # still fall through to a plain, full-refresh where filter.
        resource = get_resource("Workspaces", WORKSPACE_ID, should_use_incremental_field=True, incremental_field=None)
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        params = endpoint_config["params"]
        assert isinstance(params, dict)
        assert "where" not in params
        assert resource["write_disposition"] == "replace"

    def test_paginator_uses_the_documented_default_limit(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
            OffsetPaginator,
        )

        resource = get_resource("Companies", WORKSPACE_ID, should_use_incremental_field=False, incremental_field=None)
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        paginator = endpoint_config["paginator"]
        assert isinstance(paginator, OffsetPaginator)
        assert paginator.limit == 100
        assert paginator.total_path == "total"


class TestResolveWorkspaceId:
    def test_returns_the_single_workspace_id(self) -> None:
        response = _make_http_response({"data": [{"id": WORKSPACE_ID}], "total": 1})
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zero.zero.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = response
            assert resolve_workspace_id("api-key") == WORKSPACE_ID

    def test_raises_when_key_has_multiple_workspaces(self) -> None:
        response = _make_http_response(
            {"data": [{"id": WORKSPACE_ID}, {"id": "22222222-2222-2222-2222-222222222222"}], "total": 2}
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zero.zero.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = response
            with pytest.raises(ValueError, match="access to multiple workspaces"):
                resolve_workspace_id("api-key")

    def test_raises_when_key_has_no_workspace(self) -> None:
        response = _make_http_response({"data": [], "total": 0})
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zero.zero.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = response
            with pytest.raises(ValueError, match="isn't a member of any workspace"):
                resolve_workspace_id("api-key")

    def test_raises_on_http_error(self) -> None:
        response = _make_http_response(None, status_code=401)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zero.zero.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = response
            with pytest.raises(requests.HTTPError):
                resolve_workspace_id("api-key")


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    def test_maps_status_code_to_validity(self, status_code: int, expected: bool) -> None:
        response = _make_http_response({"data": []}, status_code=status_code)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zero.zero.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = response
            assert validate_credentials("api-key") is expected


class TestZeroSourceResumeBehavior:
    """End-to-end resume behaviour of ``zero_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response], should_use_incremental_field: bool = False
    ) -> tuple[list[list[dict[str, Any]]], list[int | None]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.zero.zero.resolve_workspace_id",
                return_value=WORKSPACE_ID,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
            ) as mock_session,
        ):
            mock_session.return_value.headers = {}
            mock_session.return_value.prepare_request.side_effect = lambda req: req
            mock_session.return_value.send.side_effect = fake_send

            resource = zero_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                should_use_incremental_field=should_use_incremental_field,
            )
            pages = list(cast(Iterable[list[dict[str, Any]]], resource))

        offsets_sent = [p.get("offset") for p in sent_params]
        return pages, offsets_sent

    def test_fresh_run_saves_offset_after_each_non_terminal_page(self) -> None:
        # The offset paginator's default limit is 100, so a non-terminal page must carry a full
        # 100 rows — anything smaller would (correctly) be read as the last page and stop pagination.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"data": [{"id": f"c{i}"} for i in range(100)], "total": 250}),
            _make_http_response({"data": [{"id": f"c{i}"} for i in range(100, 200)], "total": 250}),
            _make_http_response({"data": [{"id": f"c{i}"} for i in range(200, 250)], "total": 250}),
        ]
        pages, offsets_sent = self._drive("Companies", manager, responses)

        assert offsets_sent == [0, 100, 200]
        assert [row["id"] for page in pages for row in page] == [f"c{i}" for i in range(250)]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ZeroResumeConfig(offset=100), ZeroResumeConfig(offset=200)]

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ZeroResumeConfig(offset=200)

        responses = [_make_http_response({"data": [{"id": "c4"}], "total": 201})]
        _, offsets_sent = self._drive("Companies", manager, responses)

        assert offsets_sent == [200]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"id": "only"}], "total": 1})]
        self._drive("Companies", manager, responses)

        manager.save_state.assert_not_called()

    def test_scoped_endpoint_sends_workspace_where_filter(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"id": "c1"}], "total": 1})]
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.zero.zero.resolve_workspace_id",
                return_value=WORKSPACE_ID,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
            ) as mock_session,
        ):
            mock_session.return_value.headers = {}
            mock_session.return_value.prepare_request.side_effect = lambda req: req
            mock_session.return_value.send.side_effect = fake_send

            resource = zero_source(
                api_key="test-key",
                endpoint="Companies",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
            )
            list(cast(Iterable[Any], resource))

        assert json.loads(sent_params[0]["where"]) == {"workspaceId": WORKSPACE_ID}
