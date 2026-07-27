import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.recurly import (
    RecurlyPaginator,
    RecurlyResumeConfig,
    _extract_cursor,
    _format_datetime,
    get_resource,
    recurly_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.settings import RECURLY_ENDPOINTS

INCREMENTAL_ENDPOINTS = [name for name, e in RECURLY_ENDPOINTS.items() if e.supports_incremental]
FULL_REFRESH_ENDPOINTS = [name for name, e in RECURLY_ENDPOINTS.items() if not e.supports_incremental]


def _list_body(data: list[dict[str, Any]], has_more: bool = False, next_path: str | None = None) -> dict[str, Any]:
    return {"object": "list", "has_more": has_more, "next": next_path, "data": data}


def _resource(endpoint: str, **kwargs: Any) -> dict[str, Any]:
    # get_resource returns an EndpointResource TypedDict whose nested values are unions;
    # cast to a plain dict so the structural assertions below stay readable.
    return cast(dict[str, Any], get_resource(endpoint, **kwargs))


class TestRecurlyHelpers:
    @pytest.mark.parametrize(
        "next_path, expected",
        [
            ("/accounts?cursor=abc123&limit=200", "abc123"),
            ("/sites/subdomain-foo/accounts?sort=updated_at&cursor=zzz", "zzz"),
            ("/accounts?limit=200", None),
            ("", None),
            (None, None),
        ],
    )
    def test_extract_cursor(self, next_path, expected):
        assert _extract_cursor(next_path) == expected

    def test_format_datetime_naive_datetime_gets_utc_z_suffix(self):
        assert _format_datetime(datetime(2024, 1, 2, 3, 4, 5, 678000)) == "2024-01-02T03:04:05.678Z"

    def test_format_datetime_aware_datetime_converted_to_utc(self):
        from datetime import timedelta, timezone

        value = datetime(2024, 1, 2, 5, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        assert _format_datetime(value) == "2024-01-02T03:00:00.000Z"

    def test_format_datetime_date(self):
        assert _format_datetime(date(2024, 1, 2)) == "2024-01-02T00:00:00.000Z"

    def test_format_datetime_none(self):
        assert _format_datetime(None) is None

    def test_format_datetime_string_passthrough(self):
        assert _format_datetime("2024-01-02T00:00:00Z") == "2024-01-02T00:00:00Z"


class TestRecurlyPaginator:
    def test_initial_state(self):
        paginator = RecurlyPaginator()
        assert paginator._next_cursor is None
        # BasePaginator starts True so the first request fires; update_state flips it.
        assert paginator.has_next_page is True

    def test_update_state_has_more_extracts_cursor(self):
        paginator = RecurlyPaginator()
        response = MagicMock()
        response.json.return_value = _list_body([{"id": "a1"}], has_more=True, next_path="/accounts?cursor=next-1")
        paginator.update_state(response)
        assert paginator._next_cursor == "next-1"
        assert paginator.has_next_page is True

    def test_update_state_no_more_when_has_more_false(self):
        paginator = RecurlyPaginator()
        response = MagicMock()
        response.json.return_value = _list_body([{"id": "a1"}], has_more=False, next_path="/accounts?cursor=ignored")
        paginator.update_state(response)
        assert paginator._next_cursor is None
        assert paginator.has_next_page is False

    def test_update_state_has_more_but_missing_cursor_terminates(self):
        paginator = RecurlyPaginator()
        response = MagicMock()
        response.json.return_value = _list_body([{"id": "a1"}], has_more=True, next_path="/accounts?limit=200")
        paginator.update_state(response)
        assert paginator._next_cursor is None
        assert paginator.has_next_page is False

    def test_update_state_invalid_json_terminates(self):
        paginator = RecurlyPaginator()
        response = MagicMock()
        response.json.side_effect = ValueError("no json")
        paginator.update_state(response)
        assert paginator.has_next_page is False

    @pytest.mark.parametrize("seeded_cursor", [None, "cursor-2000"])
    def test_init_request_honours_seeded_cursor(self, seeded_cursor):
        paginator = RecurlyPaginator()
        if seeded_cursor is not None:
            paginator.set_resume_state({"next_cursor": seeded_cursor})

        request = Request(method="GET", url="https://v3.recurly.com/accounts")
        paginator.init_request(request)

        if seeded_cursor is None:
            assert request.params is None or "cursor" not in request.params
        else:
            assert request.params["cursor"] == seeded_cursor

    def test_get_resume_state_returns_state_when_next_page(self):
        paginator = RecurlyPaginator()
        response = MagicMock()
        response.json.return_value = _list_body([], has_more=True, next_path="/accounts?cursor=c-42")
        paginator.update_state(response)
        assert paginator.get_resume_state() == {"next_cursor": "c-42"}

    def test_get_resume_state_returns_none_on_terminal_page(self):
        paginator = RecurlyPaginator()
        response = MagicMock()
        response.json.return_value = _list_body([], has_more=False)
        paginator.update_state(response)
        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self):
        paginator = RecurlyPaginator()
        paginator.set_resume_state({"next_cursor": "c-99"})
        assert paginator._next_cursor == "c-99"
        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"next_cursor": "c-99"}

    def test_set_resume_state_coerces_to_string(self):
        paginator = RecurlyPaginator()
        paginator.set_resume_state({"next_cursor": 12345})
        assert paginator._next_cursor == "12345"

    def test_set_resume_state_ignores_missing_cursor(self):
        paginator = RecurlyPaginator()
        paginator.set_resume_state({})
        assert paginator._next_cursor is None


class TestGetResource:
    @pytest.mark.parametrize("endpoint", INCREMENTAL_ENDPOINTS)
    def test_full_refresh_resource_uses_replace_and_stable_sort(self, endpoint):
        resource = _resource(
            endpoint, should_use_incremental_field=False, incremental_field=None, db_incremental_field_last_value=None
        )
        assert resource["name"] == endpoint
        assert resource["table_name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == RECURLY_ENDPOINTS[endpoint].path
        assert resource["endpoint"]["data_selector"] == "data"
        params = resource["endpoint"]["params"]
        assert params["sort"] == "created_at"
        assert params["order"] == "asc"
        assert params["limit"] == 200
        assert "begin_time" not in params

    @pytest.mark.parametrize("endpoint", INCREMENTAL_ENDPOINTS)
    def test_incremental_resource_uses_merge_and_begin_time(self, endpoint):
        resource = _resource(
            endpoint,
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        params = resource["endpoint"]["params"]
        assert params["sort"] == "updated_at"
        assert params["order"] == "asc"
        assert params["begin_time"] == "2024-01-01T00:00:00.000Z"

    def test_incremental_honours_chosen_field(self):
        resource = _resource(
            "accounts",
            should_use_incremental_field=True,
            incremental_field="created_at",
            db_incremental_field_last_value=None,
        )
        assert resource["endpoint"]["params"]["sort"] == "created_at"

    def test_incremental_falls_back_to_updated_at_for_unknown_field(self):
        resource = _resource(
            "accounts",
            should_use_incremental_field=True,
            incremental_field="not_a_field",
            db_incremental_field_last_value=None,
        )
        assert resource["endpoint"]["params"]["sort"] == "updated_at"

    def test_no_begin_time_without_last_value(self):
        resource = _resource(
            "accounts",
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value=None,
        )
        assert "begin_time" not in resource["endpoint"]["params"]

    @pytest.mark.parametrize("endpoint", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoint_ignores_incremental_request(self, endpoint):
        # Even if the pipeline asks for incremental, an endpoint without a server-side
        # time filter must stay full-refresh.
        resource = _resource(
            endpoint,
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["params"]["sort"] == "created_at"
        assert "begin_time" not in resource["endpoint"]["params"]


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_status_code_mapping(self, status_code, expected_valid):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.recurly.recurly.make_tracked_session"
        ) as mock_session:
            mock_session.return_value.get.return_value = _make_http_response({}, status_code=status_code)
            is_valid, message = validate_credentials("key", "us")

        assert is_valid is expected_valid
        if not expected_valid:
            assert message

    def test_connection_error_is_invalid(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.recurly.recurly.make_tracked_session"
        ) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            is_valid, message = validate_credentials("key", "us")

        assert is_valid is False
        assert message

    @pytest.mark.parametrize("region, expected_host", [("us", "v3.recurly.com"), ("eu", "v3.eu.recurly.com")])
    def test_region_selects_host(self, region, expected_host):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.recurly.recurly.make_tracked_session"
        ) as mock_session:
            mock_session.return_value.get.return_value = _make_http_response({}, status_code=200)
            validate_credentials("key", region)

        called_url = mock_session.return_value.get.call_args.args[0]
        assert expected_host in called_url


class TestRecurlySourceResumeBehavior:
    def _drive(self, endpoint: str, manager: MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = recurly_source(
                api_key="test-key",
                region="us",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
            )
            list(cast(Iterable[Any], resource))
            return sent_params

    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self):
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_list_body([{"id": "a1"}], has_more=True, next_path="/accounts?cursor=cur-1")),
            _make_http_response(_list_body([{"id": "a2"}], has_more=True, next_path="/accounts?cursor=cur-2")),
            _make_http_response(_list_body([{"id": "a3"}], has_more=False)),
        ]
        sent_params = self._drive("accounts", manager, responses)

        assert [p.get("cursor") for p in sent_params] == [None, "cur-1", "cur-2"]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            RecurlyResumeConfig(next_cursor="cur-1"),
            RecurlyResumeConfig(next_cursor="cur-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self):
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = RecurlyResumeConfig(next_cursor="cur-resumed")

        responses = [_make_http_response(_list_body([{"id": "a4"}], has_more=False))]
        sent_params = self._drive("accounts", manager, responses)

        assert [p.get("cursor") for p in sent_params] == ["cur-resumed"]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self):
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response(_list_body([{"id": "only"}], has_more=False))]
        self._drive("accounts", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self):
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response(_list_body([{"id": "a"}], has_more=False))]
        self._drive("accounts", manager, responses)

        manager.load_state.assert_not_called()
