import json
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, cast

from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.telnyx import (
    TelnyxResumeConfig,
    _format_created_at,
    telnyx_source,
    validate_credentials,
)


class TestFormatCreatedAt:
    def test_aware_datetime_converted_to_utc(self) -> None:
        from datetime import timedelta, timezone

        tz = timezone(timedelta(hours=5))
        assert _format_created_at(datetime(2024, 1, 2, 8, 4, 5, tzinfo=tz)) == "2024-01-02T03:04:05Z"

    def test_date_becomes_midnight_utc(self) -> None:
        assert _format_created_at(date(2024, 1, 2)) == "2024-01-02T00:00:00Z"


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
