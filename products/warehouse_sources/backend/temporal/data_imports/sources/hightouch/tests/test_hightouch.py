from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.hightouch import (
    HightouchPaginator,
    HightouchResumeConfig,
    _format_hightouch_datetime,
    _hightouch_incremental_window,
    get_resource,
    hightouch_source,
    validate_credentials,
)


def _make_manager(resume_state: HightouchResumeConfig | None = None) -> Mock:
    manager = Mock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class TestHightouchTransport:
    @parameterized.expand(
        [
            # Full page and the API says there's more — keep paging.
            ("full_page_has_more", [{"id": i} for i in range(100)], {"hasMore": True}, True),
            # Full page but hasMore is false — stop without paying an extra empty request.
            ("full_page_no_more", [{"id": i} for i in range(100)], {"hasMore": False}, False),
            # hasMore missing entirely — fall back to the inherited full-page heuristic.
            ("full_page_missing_flag", [{"id": i} for i in range(100)], {}, True),
            # Short page — stop even if the API claims more (avoids an infinite loop on a
            # server that always returns hasMore=true).
            ("short_page", [{"id": 1}], {"hasMore": True}, False),
            ("empty_page", [], {"hasMore": True}, False),
        ]
    )
    def test_paginator_termination(self, _name, data, body, expected_has_next) -> None:
        paginator = HightouchPaginator(limit=100)
        request = Mock()
        request.params = {}
        paginator.init_request(request)

        response = Mock()
        response.json.return_value = {"data": data, **body}
        paginator.update_state(response, data=data)

        assert paginator.has_next_page is expected_has_next

    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45, 999999), "2026-03-01T12:30:45Z"),
            ("aware_datetime", datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC), "2026-03-01T12:30:45Z"),
            ("passthrough_string", "1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z"),
        ]
    )
    def test_format_hightouch_datetime(self, _name, value, expected) -> None:
        assert _format_hightouch_datetime(value) == expected

    def test_incremental_window_filters_server_side_via_after(self) -> None:
        window = _hightouch_incremental_window("startedAt")
        assert window["start_param"] == "after"
        assert window["cursor_path"] == "startedAt"
        assert window["convert"] is _format_hightouch_datetime

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid Hightouch API key"),
            (403, False, "Hightouch API key is missing the required permissions"),
            (500, False, "Hightouch API returned an unexpected status: 500"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.hightouch.make_tracked_session")
    def test_validate_credentials_status_mapping(self, status, expected_valid, expected_message, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status)

        result = validate_credentials(api_key="key")

        assert result == (expected_valid, expected_message)
        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.hightouch.com/api/v1/syncs"
        assert call.kwargs["headers"]["Authorization"] == "Bearer key"

    def test_get_resource_rejects_sync_runs_fanout(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(endpoint="sync_runs")

    @parameterized.expand([("syncs",), ("sources",), ("destinations",)])
    def test_get_resource_strips_credential_bearing_configuration(self, endpoint) -> None:
        # `configuration` objects carry third-party credentials (database passwords, API
        # secrets, custom auth headers) that must not land in queryable warehouse tables.
        resource = cast(dict[str, Any], get_resource(endpoint=endpoint))
        row = resource["data_map"]({"id": 1, "slug": "prod", "configuration": {"password": "hunter2"}})
        assert row == {"id": 1, "slug": "prod"}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.hightouch.rest_api_resource")
    def test_hightouch_source_resumes_from_saved_state(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_manager(HightouchResumeConfig(paginator_state={"offset": 200}))

        hightouch_source(
            api_key="key",
            endpoint="models",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        kwargs = mock_rest_api_resource.call_args.kwargs
        assert kwargs["initial_paginator_state"] == {"offset": 200}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.hightouch.rest_api_resource")
    def test_hightouch_source_saves_checkpoints_after_batches(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_manager()

        hightouch_source(
            api_key="key",
            endpoint="models",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]
        resume_hook({"offset": 100})
        manager.save_state.assert_called_once_with(HightouchResumeConfig(paginator_state={"offset": 100}))

        # A terminal (None) checkpoint is not persisted — the Redis TTL handles cleanup.
        manager.save_state.reset_mock()
        resume_hook(None)
        manager.save_state.assert_not_called()

    @parameterized.expand(
        [
            ("incremental", True, datetime(2026, 3, 1, tzinfo=UTC)),
            ("first_sync", True, None),
            ("non_incremental", False, datetime(2026, 3, 1, tzinfo=UTC)),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.hightouch.build_dependent_resource"
    )
    def test_sync_runs_passes_watermark(
        self, _name, should_use_incremental_field, last_value, mock_build_dependent_resource
    ) -> None:
        mock_build_dependent_resource.return_value = iter([])

        hightouch_source(
            api_key="key",
            endpoint="sync_runs",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
            incremental_field="startedAt",
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is should_use_incremental_field
        assert kwargs["db_incremental_field_last_value"] == last_value
        assert kwargs["incremental_field"] == "startedAt"
