import json
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.settings import ENDPOINTS, TELNYX_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.telnyx import (
    PAGE_SIZE,
    TelnyxResumeConfig,
    _format_created_at,
    get_resource,
    telnyx_source,
    validate_credentials,
)

INCREMENTAL_ENDPOINTS = sorted(name for name, endpoint in TELNYX_ENDPOINTS.items() if endpoint.incremental_field)
FULL_REFRESH_ENDPOINTS = sorted(set(ENDPOINTS) - set(INCREMENTAL_ENDPOINTS))


class TestFormatCreatedAt:
    def test_naive_datetime_treated_as_utc(self) -> None:
        assert _format_created_at(datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02T03:04:05Z"

    def test_aware_datetime_converted_to_utc(self) -> None:
        from datetime import timedelta, timezone

        tz = timezone(timedelta(hours=5))
        assert _format_created_at(datetime(2024, 1, 2, 8, 4, 5, tzinfo=tz)) == "2024-01-02T03:04:05Z"

    def test_date_becomes_midnight_utc(self) -> None:
        assert _format_created_at(date(2024, 1, 2)) == "2024-01-02T00:00:00Z"

    def test_string_passthrough(self) -> None:
        assert _format_created_at("1970-01-01T00:00:00Z") == "1970-01-01T00:00:00Z"


class TestGetResource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_resource_shape(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)
        config = TELNYX_ENDPOINTS[endpoint]

        assert resource["name"] == endpoint
        assert resource["table_name"] == config.table_name
        assert resource["table_format"] == "delta"
        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        assert endpoint_config["path"] == "/v2/detail_records"
        assert endpoint_config["data_selector"] == "data"
        assert endpoint_config["data_selector_required"] is True

        params = cast(dict[str, Any], endpoint_config["params"])
        assert params["filter[record_type]"] == config.record_type
        assert params["page[size]"] == PAGE_SIZE

    @pytest.mark.parametrize("endpoint", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoints_always_replace(self, endpoint: str) -> None:
        for should_use_incremental_field in (False, True):
            resource = get_resource(endpoint, should_use_incremental_field=should_use_incremental_field)
            assert resource["write_disposition"] == "replace"
            endpoint_config = cast(dict[str, Any], resource["endpoint"])
            params = cast(dict[str, Any], endpoint_config["params"])
            assert params["sort"] == TELNYX_ENDPOINTS[endpoint].partition_key
            assert not any(key.startswith("filter[") and key != "filter[record_type]" for key in params)

    @pytest.mark.parametrize("endpoint", INCREMENTAL_ENDPOINTS)
    def test_incremental_endpoints_full_refresh_when_disabled(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)
        assert resource["write_disposition"] == "replace"
        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        params = cast(dict[str, Any], endpoint_config["params"])
        assert params["sort"] == TELNYX_ENDPOINTS[endpoint].partition_key
        incremental_field = TELNYX_ENDPOINTS[endpoint].incremental_field
        assert f"filter[{incremental_field}][gte]" not in params

    @pytest.mark.parametrize("endpoint", INCREMENTAL_ENDPOINTS)
    def test_incremental_endpoints_merge_when_enabled(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

        incremental_field = TELNYX_ENDPOINTS[endpoint].incremental_field
        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        params = cast(dict[str, Any], endpoint_config["params"])
        assert params["sort"] == incremental_field

        filter_config = params[f"filter[{incremental_field}][gte]"]
        assert filter_config["type"] == "incremental"
        assert filter_config["cursor_path"] == incremental_field
        assert filter_config["convert"] is _format_created_at


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestTelnyxSourceResumeBehavior:
    """End-to-end pagination/resume behaviour of ``telnyx_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response], should_use_incremental_field: bool = False
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.telnyx.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = telnyx_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                should_use_incremental_field=should_use_incremental_field,
            )
            list(cast(Iterable[Any], resource))
            return mock_session, sent_params

    def test_fresh_run_walks_pages_until_total_pages(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"data": [{"uuid": "1"}], "meta": {"total_pages": 3}}),
            _make_http_response({"data": [{"uuid": "2"}], "meta": {"total_pages": 3}}),
            _make_http_response({"data": [{"uuid": "3"}], "meta": {"total_pages": 3}}),
        ]
        _, sent_params = self._drive("MessagingDetailRecords", manager, responses)

        assert [p.get("page[number]") for p in sent_params] == [1, 2, 3]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [TelnyxResumeConfig(next_page=2), TelnyxResumeConfig(next_page=3)]

    def test_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"uuid": "1"}], "meta": {"total_pages": 1}})]
        self._drive("MessagingDetailRecords", manager, responses)

        manager.save_state.assert_not_called()

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = TelnyxResumeConfig(next_page=2)

        responses = [
            _make_http_response({"data": [{"uuid": "2"}], "meta": {"total_pages": 2}}),
        ]
        _, sent_params = self._drive("MessagingDetailRecords", manager, responses)

        assert [p.get("page[number]") for p in sent_params] == [2]
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [], "meta": {"total_pages": 1}})]
        self._drive("MessagingDetailRecords", manager, responses)

        manager.load_state.assert_not_called()

    def test_incremental_run_filters_by_created_at(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"uuid": "1"}], "meta": {"total_pages": 1}})]
        _, sent_params = self._drive("VerifyDetailRecords", manager, responses, should_use_incremental_field=True)

        assert sent_params[0]["filter[created_at][gte]"] == "1970-01-01T00:00:00Z"
        assert sent_params[0]["sort"] == "created_at"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.telnyx.make_tracked_session")
    def test_status_maps_to_validity(self, mock_session_factory: MagicMock, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        mock_session_factory.return_value.get.return_value = response

        assert validate_credentials("api-key") is expected

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.telnyx.make_tracked_session")
    def test_probes_detail_records_with_bearer_auth(self, mock_session_factory: MagicMock) -> None:
        mock_get = mock_session_factory.return_value.get
        mock_get.return_value = MagicMock(status_code=200)

        validate_credentials("api-key")

        mock_session_factory.assert_called_once_with(redact_values=("api-key",), capture=False)
        called_url = mock_get.call_args.args[0]
        called_kwargs = mock_get.call_args.kwargs
        assert called_url == "https://api.telnyx.com/v2/detail_records"
        assert called_kwargs["headers"] == {"Authorization": "Bearer api-key"}
        assert called_kwargs["params"] == {"filter[record_type]": "messaging", "page[size]": 1}
