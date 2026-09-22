import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.cloudzero import (
    KEY_REJECTED_MESSAGE,
    PROBE_FAILED_MESSAGE,
    CloudzeroResumeConfig,
    _rolling_incremental_start_date,
    cloudzero_source,
    get_resource,
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


def _make_http_response(body: Any, status_code: int = 200) -> Response:
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


def _list_page(data_key: str, next_cursor: str | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        data_key: rows,
        "pagination": {
            "cursor": {
                "next_cursor": next_cursor,
                "has_next": next_cursor is not None,
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
    ) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
        """Drive ``cloudzero_source`` with a mocked HTTP session.

        Returns ``(sent_urls, sent_params, rows)``, all captured at send-time: the request URLs,
        shallow copies of ``request.params``, and the flattened rows the resource yielded.
        """
        sent_urls: list[str] = []
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_urls.append(request.url)
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
            pages = list(cast(Iterable[Any], resource))
            return sent_urls, sent_params, [row for page in pages for row in page]

    @parameterized.expand(
        [
            ("Budgets", "/v2/budgets", {"expand": ["current"]}, _list_page("budgets", None, [{"id": "b-1"}])),
            ("Dimensions", "/v2/billing/dimensions", {"include_hidden": "true"}, {"dimensions": [{"id": "service"}]}),
            ("Insights", "/v2/insights", {}, _list_page("insights", None, [{"id": "i-1"}])),
            # This endpoint answers with a bare array, so it carries no envelope key to select on.
            ("RecommendationTypes", "/v2/optimize/recommendation_types", {}, [{"id": "CIR-AWS-00216"}]),
            (
                "Recommendations",
                "/v2/optimize/recommendations",
                {"limit": 1000},
                _list_page("recommendations", None, [{"recommendation_id": "r-1"}]),
            ),
        ]
    )
    def test_list_endpoint_reads_its_own_path_params_and_envelope(
        self, endpoint: str, path: str, expected_params: dict[str, Any], body: Any
    ) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        sent_urls, sent_params, rows = self._drive(endpoint, manager, [_make_http_response(body)])

        assert sent_urls == [f"https://api.cloudzero.com{path}"]
        assert sent_params == [expected_params]
        assert len(rows) == 1

    @parameterized.expand(
        [
            ("Budgets", "budgets"),
            ("Insights", "insights"),
            ("Recommendations", "recommendations"),
        ]
    )
    def test_paginated_list_endpoint_follows_the_cursor(self, endpoint: str, data_key: str) -> None:
        # Without the cursor paginator these endpoints would sync only their first page.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_list_page(data_key, "cursor-1", [{"id": "1"}])),
            _make_http_response(_list_page(data_key, None, [{"id": "2"}])),
        ]
        _, sent_params, rows = self._drive(endpoint, manager, responses)

        assert [p.get("cursor") for p in sent_params] == [None, "cursor-1"]
        assert len(rows) == 2

    def test_costs_pages_through_cursor_and_saves_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_costs_page("cursor-1", [{"usage_date": "2025-01-01T00:00:00+00:00", "cost": 1.0}])),
            _make_http_response(_costs_page("cursor-2", [{"usage_date": "2025-01-02T00:00:00+00:00", "cost": 2.0}])),
            _make_http_response(_costs_page(None, [{"usage_date": "2025-01-03T00:00:00+00:00", "cost": 3.0}])),
        ]
        _, sent_params, _ = self._drive("Costs", manager, responses)

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
        _, sent_params, _ = self._drive("Costs", manager, responses)

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
        _, sent_params, _ = self._drive("Dimensions", manager, responses)

        assert len(sent_params) == 1
        manager.load_state.assert_not_called()

    def test_full_refresh_uses_default_start_date(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_costs_page(None, [{"usage_date": "2025-01-05T00:00:00+00:00", "cost": 5.0}])),
        ]
        _, sent_params, _ = self._drive("Costs", manager, responses)

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
        _, sent_params, _ = self._drive("Costs", manager, responses, group_by=["service", "account"])

        assert sent_params[0]["group_by"] == ["service", "account"]

    def test_granularity_and_cost_type_are_forwarded(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_costs_page(None, [{"usage_date": "2025-01-05T00:00:00+00:00", "cost": 5.0}])),
        ]
        _, sent_params, _ = self._drive("Costs", manager, responses, granularity="monthly", cost_type="billed_cost")

        assert sent_params[0]["granularity"] == "monthly"
        assert sent_params[0]["cost_type"] == "billed_cost"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, (True, None)),
            ("forbidden", 403, (False, KEY_REJECTED_MESSAGE)),
            ("unauthorized", 401, (False, KEY_REJECTED_MESSAGE)),
            # A CloudZero-side failure leaves the key unjudged, so it must not be blamed on the key.
            ("server_error", 500, (False, PROBE_FAILED_MESSAGE)),
        ]
    )
    def test_status_code_maps_to_validity(
        self, _name: str, status_code: int, expected: tuple[bool, str | None]
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.cloudzero.make_tracked_session"
        ) as mock_make_session:
            mock_response = MagicMock()
            mock_response.status_code = status_code
            mock_make_session.return_value.get.return_value = mock_response

            assert validate_credentials("test-key") == expected

    def test_does_not_blame_the_key_when_cloudzero_is_unreachable(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.cloudzero.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.side_effect = ConnectionError("boom")

            assert validate_credentials("test-key") == (False, PROBE_FAILED_MESSAGE)

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


class TestGetResource:
    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown CloudZero endpoint"):
            get_resource("NotAnEndpoint", False, "daily", "real_cost", [])
