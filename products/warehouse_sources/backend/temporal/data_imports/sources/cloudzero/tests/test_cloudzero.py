import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.cloudzero import (
    CloudzeroResumeConfig,
    _rolling_incremental_start_date,
    cloudzero_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestRollingIncrementalStartDate:
    @parameterized.expand(
        [
            ("datetime", datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC), "2026-01-08T12:00:00+00:00"),
            ("date", date(2026, 1, 15), "2026-01-08T00:00:00+00:00"),
            ("iso_string", "2026-01-15T12:00:00+00:00", "2026-01-08T12:00:00+00:00"),
            ("naive_datetime", datetime(2026, 1, 15, 12, 0, 0), "2026-01-08T12:00:00+00:00"),
        ]
    )
    def test_rolls_back_by_restatement_window(self, _name: str, value: Any, expected: str) -> None:
        # CloudZero can restate historical costs, so the incremental start_date must roll back
        # a fixed window rather than resuming exactly where the last sync left off.
        assert _rolling_incremental_start_date(value) == expected


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _costs_page(next_cursor: str | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "costs": rows,
        "pagination": {
            "page_count": 1,
            "item_count": len(rows),
            "total_count": len(rows),
            "cursor": {
                "next_cursor": next_cursor,
                "previous_cursor": None,
                "has_next": next_cursor is not None,
                "has_previous": False,
            },
        },
    }


class TestCloudzeroSourceTransport:
    """End-to-end behaviour of ``cloudzero_source`` via ``rest_api_resource``."""

    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        **kwargs: Any,
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        """Drive ``cloudzero_source`` with a mocked HTTP session.

        Returns ``(mock_session, sent_params)`` where ``sent_params`` is a list of shallow
        copies of ``request.params`` captured at send-time.
        """
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

            resource = cloudzero_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
                **kwargs,
            )
            list(cast(Iterable[Any], resource))
            return mock_session, sent_params

    def test_costs_pages_through_cursor_and_saves_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_costs_page("cursor-1", [{"usage_date": "2025-01-01T00:00:00+00:00", "cost": 1.0}])),
            _make_http_response(_costs_page("cursor-2", [{"usage_date": "2025-01-02T00:00:00+00:00", "cost": 2.0}])),
            _make_http_response(_costs_page(None, [{"usage_date": "2025-01-03T00:00:00+00:00", "cost": 3.0}])),
        ]
        _, sent_params = self._drive("Costs", manager, responses)

        cursors_sent = [p.get("cursor") for p in sent_params]
        assert cursors_sent == [None, "cursor-1", "cursor-2"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            CloudzeroResumeConfig(next_cursor="cursor-1"),
            CloudzeroResumeConfig(next_cursor="cursor-2"),
        ]

    def test_costs_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CloudzeroResumeConfig(next_cursor="cursor-resumed")

        responses = [
            _make_http_response(_costs_page(None, [{"usage_date": "2025-01-04T00:00:00+00:00", "cost": 4.0}])),
        ]
        _, sent_params = self._drive("Costs", manager, responses)

        assert [p.get("cursor") for p in sent_params] == ["cursor-resumed"]
        manager.load_state.assert_called_once()

    def test_costs_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_costs_page(None, [{"usage_date": "2025-01-05T00:00:00+00:00", "cost": 5.0}])),
        ]
        self._drive("Costs", manager, responses)

        manager.save_state.assert_not_called()

    def test_dimensions_endpoint_does_not_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"dimensions": [{"id": "service", "name": "Service"}]}),
        ]
        _, sent_params = self._drive("Dimensions", manager, responses)

        assert len(sent_params) == 1
        manager.load_state.assert_not_called()

    def test_full_refresh_uses_default_start_date(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_costs_page(None, [{"usage_date": "2025-01-05T00:00:00+00:00", "cost": 5.0}])),
        ]
        _, sent_params = self._drive("Costs", manager, responses)

        assert sent_params[0]["start_date"] == "2025-01-01T00:00:00+00:00"

    def test_incremental_rolls_start_date_back_from_watermark(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_costs_page(None, [{"usage_date": "2026-01-15T00:00:00+00:00", "cost": 5.0}])),
        ]
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

            resource = cloudzero_source(
                api_key="test-key",
                endpoint="Costs",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value="2026-01-15T00:00:00+00:00",
                should_use_incremental_field=True,
            )
            list(cast(Iterable[Any], resource))

        assert sent_params[0]["start_date"] == "2026-01-08T00:00:00+00:00"

    def test_group_by_sent_as_repeated_query_param(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(
                _costs_page(None, [{"usage_date": "2025-01-05T00:00:00+00:00", "service": "ec2", "cost": 5.0}])
            ),
        ]
        _, sent_params = self._drive("Costs", manager, responses, group_by=["service", "account"])

        assert sent_params[0]["group_by"] == ["service", "account"]

    def test_granularity_and_cost_type_are_forwarded(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_costs_page(None, [{"usage_date": "2025-01-05T00:00:00+00:00", "cost": 5.0}])),
        ]
        _, sent_params = self._drive("Costs", manager, responses, granularity="monthly", cost_type="billed_cost")

        assert sent_params[0]["granularity"] == "monthly"
        assert sent_params[0]["cost_type"] == "billed_cost"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("forbidden", 403, False),
            ("unauthorized", 401, False),
        ]
    )
    def test_status_code_maps_to_validity(self, _name: str, status_code: int, expected: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.cloudzero.make_tracked_session"
        ) as mock_make_session:
            mock_response = MagicMock()
            mock_response.status_code = status_code
            mock_make_session.return_value.get.return_value = mock_response

            assert validate_credentials("test-key") is expected

    def test_sends_raw_api_key_without_bearer_prefix(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.cloudzero.make_tracked_session"
        ) as mock_make_session:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_session = mock_make_session.return_value
            mock_session.get.return_value = mock_response

            validate_credentials("raw-key-123")

            _, kwargs = mock_session.get.call_args
            assert kwargs["headers"]["Authorization"] == "raw-key-123"
