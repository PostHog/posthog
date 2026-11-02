from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import Mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hightouch import (
    HightouchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.hightouch import (
    HightouchPaginator,
    HightouchResumeConfig,
    _format_hightouch_datetime,
    _hightouch_incremental_window,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.source import HightouchSource


def _driver() -> SourceDriver:
    return SourceDriver(HightouchSource(), HightouchSourceConfig(api_key="key"))


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
    def test_validate_credentials_status_mapping(
        self, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            result = validate_credentials(api_key="key")

        assert result == (expected_valid, expected_message)
        assert {request.method for request in network.requests_log} == {"GET"}
        assert {request.origin for request in network.requests_log} == {"https://api.hightouch.com"}
        assert {request.path for request in network.requests_log} == {"/api/v1/syncs"}
        assert {request.param("limit") for request in network.requests_log} == {"1"}
        assert {request.headers["authorization"] for request in network.requests_log} == {"Bearer key"}
        assert network.session_options == [{"capture": False, "redact_values": ("key",)}]

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

    def test_hightouch_source_resumes_from_saved_state(self) -> None:
        result = _driver().run(
            "models",
            [ScriptedResponse(json={"data": [{"id": 201}], "hasMore": False})],
            resume_state=HightouchResumeConfig(paginator_state={"offset": 200}),
        )

        assert result.raised is None
        assert result.rows == [{"id": 201}]
        assert result.params("offset") == ["200"]

    def test_hightouch_source_saves_checkpoints_after_batches(self) -> None:
        result = _driver().run(
            "models",
            [
                ScriptedResponse(json={"data": [{"id": i} for i in range(100)], "hasMore": True}),
                ScriptedResponse(json={"data": [{"id": 100}], "hasMore": False}),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 101
        assert result.params("offset") == ["0", "100"]
        # A terminal (None) checkpoint is not persisted — the Redis TTL handles cleanup.
        assert result.saved_states == [HightouchResumeConfig(paginator_state={"offset": 100})]
        assert result.committed_states == [HightouchResumeConfig(paginator_state={"offset": 100})]

    @parameterized.expand(
        [
            ("incremental", True, datetime(2026, 3, 1, tzinfo=UTC), "2026-03-01T00:00:00Z"),
            ("first_sync", True, None, "1970-01-01T00:00:00Z"),
            ("non_incremental", False, datetime(2026, 3, 1, tzinfo=UTC), None),
        ]
    )
    def test_sync_runs_passes_watermark(
        self, _name: str, should_use_incremental_field: bool, last_value: datetime | None, expected_after: str | None
    ) -> None:
        result = _driver().run(
            "sync_runs",
            [
                ScriptedResponse(json={"data": [{"id": 1}], "hasMore": False}),
                ScriptedResponse(json={"data": [{"id": 2, "startedAt": "2026-03-02T00:00:00Z"}], "hasMore": False}),
            ],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
            incremental_field="startedAt" if should_use_incremental_field else None,
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/syncs", "/api/v1/syncs/1/runs"]
        assert result.requests[0].param("after") is None
        assert result.requests[1].param("after") == expected_after
        assert result.rows == [{"id": 2, "startedAt": "2026-03-02T00:00:00Z", "sync_id": 1}]
