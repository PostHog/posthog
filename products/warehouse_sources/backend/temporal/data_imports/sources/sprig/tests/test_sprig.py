from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.settings import ENDPOINTS, SPRIG_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.sprig import (
    SprigResumeConfig,
    _format_incremental_value,
    get_resource,
    sprig_source,
    validate_credentials,
)


def _response(body: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = body
    return response


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("none_passthrough", None, None),
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), 1772593094000),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), 1772593094000),
            ("date_value", date(2026, 3, 4), 1772582400000),
            ("int_passthrough", 1772582400000, 1772582400000),
            ("float_truncated", 1772582400000.9, 1772582400000),
            ("iso_string", "2026-03-04T02:58:14+00:00", 1772593094000),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_format(self, _label: str, value: Any, expected: Any) -> None:
        assert _format_incremental_value(value) == expected


class TestGetResource:
    @staticmethod
    def _params(resource: Any) -> dict[str, Any]:
        endpoint = cast(dict[str, Any], resource["endpoint"])
        return cast(dict[str, Any], endpoint["params"])

    @parameterized.expand(list(ENDPOINTS))
    def test_resource_shape(self, endpoint: str) -> None:
        cfg = SPRIG_ENDPOINTS[endpoint]
        resource = get_resource(endpoint, should_use_incremental_field=False)
        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        params = self._params(resource)

        assert resource["name"] == cfg.name
        assert resource["table_name"] == cfg.table_name
        assert resource["table_format"] == "delta"
        assert endpoint_config["path"] == cfg.path
        assert endpoint_config["data_selector"] == "data"
        assert params["limit"] == 1000
        assert "start" not in params
        assert resource["write_disposition"] == "replace"

    @parameterized.expand(list(ENDPOINTS))
    def test_incremental_resource_sets_filter_and_merges(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        param = cast(dict[str, Any], self._params(resource)["start"])
        assert param["type"] == "incremental"
        assert param["cursor_path"] == "createdAt"
        assert param["convert"] is _format_incremental_value

    def test_responses_primary_key_includes_question_id(self) -> None:
        assert SPRIG_ENDPOINTS["Responses"].primary_keys == ["responseGroupUid", "questionId"]

    def test_surveys_primary_key_is_id(self) -> None:
        assert SPRIG_ENDPOINTS["Surveys"].primary_keys == ["id"]


class TestSprigCursorPaginator:
    def _paginator(self) -> JSONResponseCursorPaginator:
        return JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor")

    def test_initial_state(self) -> None:
        paginator = self._paginator()
        assert paginator.has_next_page is True

    def test_update_state_has_more(self) -> None:
        paginator = self._paginator()
        paginator.update_state(_response({"data": [{"id": 1}], "cursor": "cursor-1"}))
        assert paginator.has_next_page is True

    @parameterized.expand([("null_cursor", None), ("missing_cursor_key", "missing")])
    def test_update_state_terminal_page(self, _label: str, cursor_value: str | None) -> None:
        paginator = self._paginator()
        body: dict[str, Any] = {"data": [{"id": 1}]}
        if cursor_value != "missing":
            body["cursor"] = cursor_value
        paginator.update_state(_response(body))
        assert paginator.has_next_page is False

    def test_update_request_adds_cursor_param(self) -> None:
        paginator = self._paginator()
        paginator.update_state(_response({"data": [], "cursor": "cursor-2"}))
        request = MagicMock()
        request.params = {"limit": 1000}
        paginator.update_request(request)
        assert request.params["cursor"] == "cursor-2"

    def test_resume_state_round_trip(self) -> None:
        paginator = self._paginator()
        paginator.update_state(_response({"data": [], "cursor": "cursor-3"}))
        assert paginator.get_resume_state() == {"cursor": "cursor-3"}

        resumed = self._paginator()
        resumed.set_resume_state({"cursor": "cursor-3"})
        request = MagicMock()
        request.params = {}
        resumed.init_request(request)
        assert request.params["cursor"] == "cursor-3"

    def test_no_resume_state_on_terminal_page(self) -> None:
        paginator = self._paginator()
        paginator.update_state(_response({"data": [], "cursor": None}))
        assert paginator.get_resume_state() is None


class TestSprigSource:
    def _manager(self, *, can_resume: bool, state: SprigResumeConfig | None = None) -> MagicMock:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = can_resume
        manager.load_state.return_value = state
        return manager

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sprig.sprig.rest_api_resource")
    def test_source_response_fields(self, mock_rest: MagicMock) -> None:
        mock_resource = MagicMock()
        mock_resource.name = "Surveys"
        mock_resource.column_hints = None
        mock_rest.return_value = mock_resource

        response = sprig_source(
            api_key="key",
            endpoint="Surveys",
            team_id=1,
            job_id="job",
            resumable_source_manager=self._manager(can_resume=False),
            db_incremental_field_last_value=None,
            should_use_incremental_field=False,
        )

        assert response.name == "Surveys"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sprig.sprig.rest_api_resource")
    def test_responses_primary_key_plumbed_through(self, mock_rest: MagicMock) -> None:
        mock_resource = MagicMock()
        mock_resource.name = "Responses"
        mock_resource.column_hints = None
        mock_rest.return_value = mock_resource

        response = sprig_source(
            api_key="key",
            endpoint="Responses",
            team_id=1,
            job_id="job",
            resumable_source_manager=self._manager(can_resume=False),
            db_incremental_field_last_value=None,
        )

        assert response.primary_keys == ["responseGroupUid", "questionId"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sprig.sprig.rest_api_resource")
    def test_seeds_initial_paginator_state_from_saved_cursor(self, mock_rest: MagicMock) -> None:
        mock_rest.return_value = MagicMock(name="Surveys", column_hints=None)
        manager = self._manager(can_resume=True, state=SprigResumeConfig(next_cursor="saved-cursor"))

        sprig_source(
            api_key="key",
            endpoint="Surveys",
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=None,
        )

        _, kwargs = mock_rest.call_args
        assert kwargs["initial_paginator_state"] == {"cursor": "saved-cursor"}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sprig.sprig.rest_api_resource")
    def test_resume_hook_saves_state_after_batch(self, mock_rest: MagicMock) -> None:
        mock_rest.return_value = MagicMock(name="Surveys", column_hints=None)
        manager = self._manager(can_resume=False)

        sprig_source(
            api_key="key",
            endpoint="Surveys",
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=None,
        )

        _, kwargs = mock_rest.call_args
        resume_hook = kwargs["resume_hook"]

        resume_hook({"cursor": "next-1"})
        manager.save_state.assert_called_once_with(SprigResumeConfig(next_cursor="next-1"))

        manager.save_state.reset_mock()
        resume_hook(None)
        manager.save_state.assert_not_called()


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sprig.sprig.make_tracked_session")
    def test_status_mapping(self, _label: str, status_code: int, expected: bool, mock_session: MagicMock) -> None:
        response = MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key") is expected

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sprig.sprig.make_tracked_session")
    def test_transient_errors_raise(self, _label: str, status_code: int, mock_session: MagicMock) -> None:
        response = MagicMock()
        response.status_code = status_code
        response.raise_for_status.side_effect = HTTPError
        mock_session.return_value.get.return_value = response

        with pytest.raises(HTTPError):
            validate_credentials("key")
