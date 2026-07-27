import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.close.close import (
    INITIAL_INCREMENTAL_VALUE,
    CloseOffsetPaginator,
    CloseResumeConfig,
    _format_close_datetime,
    close_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestCloseOffsetPaginator:
    def test_initial_state(self) -> None:
        paginator = CloseOffsetPaginator()
        assert paginator.offset == 0
        assert paginator.limit == 100
        # BasePaginator starts with _has_next_page=True so the first request runs.
        assert paginator.has_next_page is True

    def test_init_request_sets_skip_and_limit(self) -> None:
        paginator = CloseOffsetPaginator()
        request = Request(method="GET", url="https://api.close.com/api/v1/lead/")
        paginator.init_request(request)
        assert request.params["_skip"] == 0
        assert request.params["_limit"] == 100

    def test_update_state_has_more_advances_offset(self) -> None:
        paginator = CloseOffsetPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [{"id": "lead_1"}], "has_more": True}
        paginator.update_state(response, [{"id": "lead_1"}])
        assert paginator.offset == 100
        assert paginator.has_next_page is True

    def test_update_state_no_more_stops(self) -> None:
        paginator = CloseOffsetPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [{"id": "lead_1"}], "has_more": False}
        paginator.update_state(response, [{"id": "lead_1"}])
        assert paginator.has_next_page is False

    def test_update_state_missing_has_more_stops(self) -> None:
        # Small dimension endpoints (statuses, pipelines) omit has_more.
        paginator = CloseOffsetPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [{"id": "stat_1"}]}
        paginator.update_state(response, [{"id": "stat_1"}])
        assert paginator.has_next_page is False

    def test_update_state_empty_page_stops(self) -> None:
        paginator = CloseOffsetPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [], "has_more": True}
        paginator.update_state(response, [])
        assert paginator.has_next_page is False

    def test_get_resume_state_when_next_page(self) -> None:
        paginator = CloseOffsetPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [{"id": "lead_1"}], "has_more": True}
        paginator.update_state(response, [{"id": "lead_1"}])
        assert paginator.get_resume_state() == {"skip": 100}

    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = CloseOffsetPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [{"id": "lead_1"}], "has_more": False}
        paginator.update_state(response, [{"id": "lead_1"}])
        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self) -> None:
        paginator = CloseOffsetPaginator()
        paginator.set_resume_state({"skip": 300})
        assert paginator.offset == 300
        assert paginator.has_next_page is True

    def test_set_resume_state_coerces_to_int(self) -> None:
        paginator = CloseOffsetPaginator()
        paginator.set_resume_state({"skip": "500"})
        assert paginator.offset == 500

    def test_set_resume_state_ignores_missing_skip(self) -> None:
        paginator = CloseOffsetPaginator()
        paginator.set_resume_state({})
        assert paginator.offset == 0


class TestFormatCloseDatetime:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05+00:00"),
            (date(2024, 1, 2), "2024-01-02T00:00:00+00:00"),
            ("2024-01-02T03:04:05+00:00", "2024-01-02T03:04:05+00:00"),
        ],
    )
    def test_formats_to_iso8601_utc(self, value: Any, expected: str) -> None:
        assert _format_close_datetime(value) == expected

    def test_naive_datetime_gets_utc(self) -> None:
        assert _format_close_datetime(datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02T03:04:05+00:00"

    def test_unparseable_value_falls_back_to_str(self) -> None:
        assert _format_close_datetime("not-a-date") == "not-a-date"


def _endpoint(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], resource["endpoint"])


def _params(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], _endpoint(resource)["params"])


class TestGetResource:
    @pytest.mark.parametrize(
        ("endpoint", "table_name"),
        [
            ("Leads", "leads"),
            ("Contacts", "contacts"),
            ("Opportunities", "opportunities"),
            ("Activities", "activities"),
            ("Tasks", "tasks"),
            ("Users", "users"),
            ("LeadStatuses", "lead_statuses"),
            ("OpportunityStatuses", "opportunity_statuses"),
            ("Pipelines", "pipelines"),
            ("EmailTemplates", "email_templates"),
        ],
    )
    def test_table_name_and_primary_key(self, endpoint: str, table_name: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False, incremental_field=None)
        assert resource["table_name"] == table_name
        assert resource["primary_key"] == ["id"]
        assert _endpoint(resource)["data_selector"] == "data"

    @pytest.mark.parametrize("endpoint", ["Leads", "Contacts", "Users", "Pipelines"])
    def test_full_refresh_endpoints_never_incremental(self, endpoint: str) -> None:
        # Even when the user enables incremental, endpoints with no server-side date filter
        # stay on full replace and emit no `__gte` param.
        resource = get_resource(endpoint, should_use_incremental_field=True, incremental_field="date_created")
        assert resource["write_disposition"] == "replace"
        assert not any(key.endswith("__gte") for key in _params(resource))

    def test_incremental_endpoint_uses_selected_cursor(self) -> None:
        resource = get_resource("Opportunities", should_use_incremental_field=True, incremental_field="date_updated")
        params = _params(resource)
        assert "date_updated__gte" in params
        gte = cast(dict[str, Any], params["date_updated__gte"])
        assert gte["cursor_path"] == "date_updated"
        assert params["_order_by"] == "date_updated"
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    @pytest.mark.parametrize("incremental_field", [None, "bogus_field"])
    def test_incremental_falls_back_to_first_advertised_cursor(self, incremental_field: str | None) -> None:
        resource = get_resource("Opportunities", should_use_incremental_field=True, incremental_field=incremental_field)
        params = _params(resource)
        assert "date_created__gte" in params
        assert params["_order_by"] == "date_created"

    def test_incremental_disabled_when_not_requested(self) -> None:
        resource = get_resource("Activities", should_use_incremental_field=False, incremental_field="date_created")
        assert resource["write_disposition"] == "replace"
        assert not any(key.endswith("__gte") for key in _params(resource))

    @pytest.mark.parametrize("endpoint", ["LeadStatuses", "OpportunityStatuses", "Pipelines"])
    def test_non_paginated_endpoints_use_single_page_paginator(self, endpoint: str) -> None:
        # Dimension endpoints that take no `_skip`/`_limit` override the client offset paginator
        # so we never inject pagination params the API doesn't accept.
        resource = get_resource(endpoint, should_use_incremental_field=False, incremental_field=None)
        assert isinstance(_endpoint(resource)["paginator"], SinglePagePaginator)

    @pytest.mark.parametrize("endpoint", ["Leads", "Contacts", "Opportunities", "Activities", "Tasks", "Users"])
    def test_paginated_endpoints_inherit_client_paginator(self, endpoint: str) -> None:
        # Offset-paginated endpoints don't set an endpoint-level paginator, so they fall back to
        # the client-level CloseOffsetPaginator.
        resource = get_resource(endpoint, should_use_incremental_field=False, incremental_field=None)
        assert "paginator" not in _endpoint(resource)


class TestCloseSourcePartitioning:
    @pytest.mark.parametrize(
        ("endpoint", "expects_partition"),
        [
            ("Leads", True),
            ("Contacts", True),
            ("Opportunities", True),
            ("Activities", True),
            ("Tasks", True),
            ("Users", False),
            ("LeadStatuses", False),
            ("Pipelines", False),
        ],
    )
    def test_partition_config(self, endpoint: str, expects_partition: bool) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        response = close_source(
            api_key="test-key",
            endpoint=endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=None,
            should_use_incremental_field=False,
        )

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        if expects_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["date_created"]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestCloseSourceResumeBehavior:
    """End-to-end resume behaviour of ``close_source`` via ``rest_api_resource``."""

    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        incremental_field: str | None = None,
        db_incremental_field_last_value: Any = None,
    ) -> list[dict[str, Any]]:
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

            resource = close_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
            )
            list(cast(Iterable[Any], resource.items()))
            return sent_params

    def test_fresh_run_saves_skip_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"data": [{"id": "lead_1"}], "has_more": True}),
            _make_http_response({"data": [{"id": "lead_2"}], "has_more": True}),
            _make_http_response({"data": [{"id": "lead_3"}], "has_more": False}),
        ]
        sent_params = self._drive("Leads", manager, responses)

        assert [p.get("_skip") for p in sent_params] == [0, 100, 200]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [CloseResumeConfig(next_skip=100), CloseResumeConfig(next_skip=200)]

    def test_resume_seeds_paginator_with_saved_skip(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CloseResumeConfig(next_skip=200)

        responses = [_make_http_response({"data": [{"id": "lead_9"}], "has_more": False})]
        sent_params = self._drive("Leads", manager, responses)

        assert [p.get("_skip") for p in sent_params] == [200]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"id": "only"}], "has_more": False})]
        self._drive("Leads", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"id": "a"}], "has_more": False})]
        self._drive("Leads", manager, responses)

        manager.load_state.assert_not_called()

    def test_incremental_request_carries_gte_and_order_by(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"id": "oppo_1"}], "has_more": False})]
        sent_params = self._drive(
            "Opportunities",
            manager,
            responses,
            should_use_incremental_field=True,
            incremental_field="date_created",
            db_incremental_field_last_value=None,
        )

        assert sent_params[0]["date_created__gte"] == INITIAL_INCREMENTAL_VALUE
        assert sent_params[0]["_order_by"] == "date_created"

    def test_incremental_request_uses_db_last_value(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"id": "oppo_1"}], "has_more": False})]
        sent_params = self._drive(
            "Opportunities",
            manager,
            responses,
            should_use_incremental_field=True,
            incremental_field="date_updated",
            db_incremental_field_last_value=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
        )

        assert sent_params[0]["date_updated__gte"] == "2024-06-01T12:00:00+00:00"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.close.close.make_tracked_session")
    def test_status_code_mapping(self, mock_session: MagicMock, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("api_test") is expected

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.close.close.make_tracked_session")
    def test_network_error_returns_false(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("api_test") is False
