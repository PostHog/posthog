import json
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.pluralsight_flow import (
    PluralsightFlowResumeConfig,
    _core_resource,
    _default_metrics_date_range,
    _format_incremental_value,
    _metrics_resource,
    normalize_workspace,
    pluralsight_flow_source,
    validate_credentials,
)


class TestNormalizeWorkspace:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("acme", "acme"),
            ("acme-test", "acme-test"),
            ("acme2024", "acme2024"),
            ("acme.appfireflow.com", "acme"),
            ("https://acme.appfireflow.com", "acme"),
            ("https://acme.appfireflow.com/", "acme"),
        ],
    )
    def test_accepts_and_normalizes_valid_workspaces(self, raw, expected):
        assert normalize_workspace(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "acme/evil.com",
            "acme@evil.com",
            "evil.com/acme",
            "",
            "-acme",
        ],
    )
    def test_rejects_invalid_workspaces(self, raw):
        with pytest.raises(ValueError, match="Invalid Flow workspace"):
            normalize_workspace(raw)


class TestFormatIncrementalValue:
    def test_formats_datetime(self):
        assert _format_incremental_value(datetime(2024, 3, 5, 12, 30, 45)) == "2024-03-05T12:30:45"

    def test_formats_date(self):
        assert _format_incremental_value(date(2024, 3, 5)) == "2024-03-05T00:00:00"

    def test_passes_through_already_formatted_string(self):
        # The `initial_value` seed for a never-synced schema is already a formatted string.
        assert _format_incremental_value("1970-01-01T00:00:00") == "1970-01-01T00:00:00"


class TestDefaultMetricsDateRange:
    def test_builds_trailing_window(self):
        assert _default_metrics_date_range(today=date(2026, 4, 30)) == "[2026-01-30:2026-04-30]"


def _endpoint_params(resource: EndpointResource) -> dict[str, Any]:
    # `endpoint` is typed as `str | Endpoint | None` (a dlt-style shorthand union), so mypy can't
    # index into it directly even though these tests only ever build the dict form.
    endpoint = cast(dict[str, Any], resource["endpoint"])
    return cast(dict[str, Any], endpoint["params"])


class TestCoreResource:
    def test_incremental_endpoint_sets_merge_disposition_and_filter_param(self):
        resource = _core_resource("Commits", should_use_incremental_field=True)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        assert resource["table_name"] == "commits"
        params = _endpoint_params(resource)
        assert "author_date__gte" in params
        assert params["author_date__gte"]["type"] == "incremental"

    def test_incremental_endpoint_without_incremental_flag_is_full_refresh(self):
        resource = _core_resource("Commits", should_use_incremental_field=False)

        assert resource["write_disposition"] == "replace"
        params = _endpoint_params(resource)
        assert params == {}

    def test_endpoint_with_no_incremental_fields_ignores_the_flag(self):
        # Repos has no INCREMENTAL_FIELDS entry, so even should_use_incremental_field=True
        # must not add a filter param.
        resource = _core_resource("Repos", should_use_incremental_field=True)

        assert resource["write_disposition"] == "replace"
        params = _endpoint_params(resource)
        assert params == {}


class TestMetricsResource:
    def test_stamps_date_range_onto_each_row(self):
        resource = _metrics_resource("CodingMetrics", "[2026-01-01:2026-04-01]")
        data_map = resource["data_map"]
        assert data_map is not None

        row = data_map({"time_to_merge": {"average": 3.2}})
        assert row == {"time_to_merge": {"average": 3.2}, "date_range": "[2026-01-01:2026-04-01]"}


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestPluralsightFlowSourceCoreEndpoints:
    """End-to-end pagination/resume behaviour of core endpoints via `rest_api_resource`."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response], should_use_incremental_field: bool = False
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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

            source_response = pluralsight_flow_source(
                api_key="test-key",
                workspace="acme",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=None,
            )
            # Iterating a Resource yields one page (list[dict]) per response, not flat rows.
            pages = list(cast(Iterable[list[dict[str, Any]]], source_response.items()))
            rows = [row for page in pages for row in page]
            return rows, sent_params

    def test_paginates_until_short_page_and_saves_resume_offset(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        # A page exactly `limit` (1000) long doesn't tell the paginator it's the last page — only
        # a page shorter than `limit` does, so the first fake page must be full-sized.
        full_page = [{"id": i} for i in range(1000)]
        responses = [
            _make_http_response({"count": 1001, "next": "...", "previous": None, "results": full_page}),
            _make_http_response({"count": 1001, "next": None, "previous": "...", "results": [{"id": 1000}]}),
        ]
        rows, sent_params = self._drive("Repos", manager, responses)

        assert rows == [*full_page, {"id": 1000}]
        # OffsetPaginator always injects `offset` (starting at 0), unlike a bespoke paginator
        # that only adds it once seeded.
        assert [p.get("offset") for p in sent_params] == [0, 1000]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [PluralsightFlowResumeConfig(offset=1000)]

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = PluralsightFlowResumeConfig(offset=2000)

        responses = [_make_http_response({"count": 1, "next": None, "previous": None, "results": [{"id": 5}]})]
        rows, sent_params = self._drive("Repos", manager, responses)

        assert rows == [{"id": 5}]
        assert sent_params[0].get("offset") == 2000
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"count": 1, "next": None, "previous": None, "results": [{"id": 1}]})]
        self._drive("Repos", manager, responses)

        manager.save_state.assert_not_called()

    def test_incremental_endpoint_sends_gte_filter(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"count": 1, "next": None, "previous": None, "results": [{"id": 1}]})]
        _, sent_params = self._drive("Commits", manager, responses, should_use_incremental_field=True)

        assert sent_params[0].get("author_date__gte") == "1970-01-01T00:00:00"


class TestPluralsightFlowSourceMetricsEndpoints:
    def test_single_object_response_yields_one_row_with_date_range(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)

        response = _make_http_response({"time_to_merge": {"average": 3.5, "trend": 0.1}})

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = lambda request, *a, **kw: response

            source_response = pluralsight_flow_source(
                api_key="test-key",
                workspace="acme",
                endpoint="CollaborationMetrics",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
            pages = list(cast(Iterable[list[dict[str, Any]]], source_response.items()))
            rows = [row for page in pages for row in page]

        assert len(rows) == 1
        assert rows[0]["time_to_merge"] == {"average": 3.5, "trend": 0.1}
        assert "date_range" in rows[0]
        manager.save_state.assert_not_called()


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [(200, True), (401, False), (403, False)],
    )
    def test_maps_status_to_validity(self, status_code, expected_valid) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.pluralsight_flow"
            ".make_tracked_session"
        ) as mock_make_session:
            mock_session = mock_make_session.return_value
            mock_session.get.return_value = _make_http_response({}, status_code=status_code)

            is_valid, status = validate_credentials("test-key", "acme")

        assert is_valid is expected_valid
        assert status == status_code

    def test_invalid_workspace_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid Flow workspace"):
            validate_credentials("test-key", "a/b")
