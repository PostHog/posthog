from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.leexi import LeexiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.leexi import (
    LeexiResumeConfig,
    _make_session,
    _to_leexi_timestamp,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.settings import ENDPOINTS, LEEXI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.source import LeexiSource


# The source builds its own capture-disabled session and hands it to RESTClient via the client config.
def _driver() -> SourceDriver:
    return SourceDriver(LeexiSource(), LeexiSourceConfig(api_key_id="key-id", api_key_secret="key-secret"))


def _page(items: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "pagination": {"page": 1, "items": len(items), "count": len(items)}})


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "users",
            [_page([{"uuid": "9"}])],
            resume_state=LeexiResumeConfig(paginator_state={"page": 7}),
        )

        assert result.raised is None
        assert [row["uuid"] for row in result.rows] == ["9"]
        assert result.params("page") == ["7"]


class TestCallsIncremental:
    @pytest.mark.parametrize("cursor_field", ["created_at", "performed_at"])
    def test_incremental_honors_user_chosen_cursor_field(self, cursor_field: str) -> None:
        result = _driver().run("calls", [_page([])], incremental_field=cursor_field)

        assert result.raised is None
        assert result.requests[0].param("date_filter") == cursor_field
        assert result.requests[0].param("order") == f"{cursor_field} asc"

    def test_incremental_rejects_unsupported_cursor_field(self) -> None:
        result = _driver().run("calls", [], incremental_field="start_time")

        assert isinstance(result.raised, ValueError)
        assert "start_time" in str(result.raised)
        assert result.requests == []

    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 1, 15, 12, 30, 45, tzinfo=UTC), "2026-01-15T12:30:45.000Z"),
            (datetime(2026, 1, 15, 12, 30, 45), "2026-01-15T12:30:45.000Z"),
            ("2026-01-15T12:30:45.123Z", "2026-01-15T12:30:45.000Z"),
            ("2026-01-15", "2026-01-15T00:00:00.000Z"),
        ],
    )
    def test_to_leexi_timestamp_formats(self, value: Any, expected: str) -> None:
        assert _to_leexi_timestamp(value) == expected


class TestCallNotesFanOut:
    def test_fans_out_one_request_per_call_and_injects_call_uuid(self) -> None:
        result = _driver().run(
            "call_notes",
            [
                _page([{"uuid": "C1"}, {"uuid": "C2"}]),
                _page([{"uuid": "n1"}]),
                _page([{"uuid": "n2"}]),
            ],
        )

        assert result.raised is None
        assert [(row["uuid"], row["call_uuid"]) for row in result.rows] == [("n1", "C1"), ("n2", "C2")]
        assert result.paths == ["/v1/calls", "/v1/call_notes", "/v1/call_notes"]
        assert result.params("call_uuid") == [None, "C1", "C2"]
        # The parent listing must not pay for transcripts it never surfaces.
        assert result.requests[0].param("with_simple_transcript") is None


class TestSourceResponseMetadata:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        if endpoint == "call_notes":
            assert response.primary_keys == ["call_uuid", "uuid"]
        else:
            assert response.primary_keys == ["uuid"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [LEEXI_ENDPOINTS[endpoint].partition_key]
        assert response.sort_mode == "asc"


class TestSampleCaptureDisabled:
    """Leexi call responses carry `simple_transcript`, notes, and free-form customer text; both the
    sync and probe sessions must disable HTTP sample capture so those bodies never land in the shared
    sample store outside the warehouse table's access controls."""

    def test_make_session_disables_capture_and_redacts_secret(self) -> None:
        with scripted_network([]) as network:
            _make_session("key-secret")

        assert network.session_options == [{"redact_values": ("key-secret",), "capture": False}]

    def test_probe_session_created_with_capture_disabled(self) -> None:
        with scripted_network([ScriptedResponse(json={"data": []})]) as network:
            status = probe_endpoint("key-id", "key-secret", "/calls")

        assert status == 200
        assert network.session_options == [{"redact_values": ("key-secret",), "capture": False}]
        assert [request.param("items") for request in network.requests_log] == ["1"]
