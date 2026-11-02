from datetime import UTC, datetime

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shipmail import (
    ShipmailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipmail.shipmail import (
    SHIPMAIL_BASE_URL,
    ShipmailResumeConfig,
    _incremental_value,
    get_capabilities,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipmail.source import ShipmailSource


def _driver() -> SourceDriver:
    return SourceDriver(ShipmailSource(), ShipmailSourceConfig(api_key="test-key"))


def test_incremental_value_preserves_iso_timestamp() -> None:
    value = datetime(2026, 7, 29, 12, 30, tzinfo=UTC)
    assert _incremental_value(value) == "2026-07-29T12:30:00+00:00"
    assert _incremental_value("2026-07-29T12:30:00Z") == "2026-07-29T12:30:00Z"


def test_messages_paginates_checkpoints_and_sends_incremental_watermark() -> None:
    result = _driver().run(
        "messages",
        [
            ScriptedResponse(
                json={
                    "data": [{"id": "msg_1"}],
                    "pagination": {"next_cursor": "cursor_2", "has_more": True, "limit": 100},
                }
            ),
            ScriptedResponse(
                json={
                    "data": [{"id": "msg_2"}],
                    "pagination": {"next_cursor": None, "has_more": False, "limit": 100},
                }
            ),
        ],
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-07-01T00:00:00Z",
        incremental_field="updated_at",
    )

    assert result.rows == [{"id": "msg_1"}, {"id": "msg_2"}]
    assert result.queries[0] == {"limit": ("100",), "updated_after": ("2026-07-01T00:00:00Z",)}
    assert result.queries[1] == {
        "limit": ("100",),
        "updated_after": ("2026-07-01T00:00:00Z",),
        "cursor": ("cursor_2",),
    }
    assert result.saved_states == [ShipmailResumeConfig(cursor="cursor_2")]
    assert result.session_options == [{"redact_values": ("test-key",), "capture": False}]


def test_resumes_from_saved_cursor() -> None:
    result = _driver().run(
        "mailboxes",
        [
            ScriptedResponse(
                json={
                    "data": [{"id": "mbx_2"}],
                    "pagination": {"next_cursor": None, "has_more": False, "limit": 100},
                }
            )
        ],
        resume_state=ShipmailResumeConfig(cursor="cursor_2"),
    )

    assert result.rows == [{"id": "mbx_2"}]
    assert result.queries[0] == {"limit": ("100",), "cursor": ("cursor_2",)}


def test_full_refresh_endpoint_does_not_send_incremental_watermark() -> None:
    result = _driver().run(
        "domains",
        [
            ScriptedResponse(
                json={
                    "data": [{"id": "domain_1"}],
                    "pagination": {"next_cursor": None, "has_more": False, "limit": 100},
                }
            )
        ],
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-07-01T00:00:00Z",
        incremental_field="updated_at",
    )

    assert result.queries[0] == {"limit": ("100",)}


def test_missing_data_key_raises() -> None:
    result = _driver().run("messages", [ScriptedResponse(json={"pagination": {"next_cursor": None}})])

    assert isinstance(result.raised, ValueError)
    assert "matched nothing" in str(result.raised)


def test_get_capabilities_returns_status_and_scopes() -> None:
    with scripted_network([ScriptedResponse(json={"scopes": ["messages:read", "domains:read"]})]) as network:
        assert get_capabilities("secret-key") == (200, {"messages:read", "domains:read"})

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.url == f"{SHIPMAIL_BASE_URL}/capabilities"
    assert request.headers["authorization"] == "Bearer secret-key"
    assert request.headers["accept"] == "application/json"
    assert request.read_timeout == 10
    assert network.session_options == [{"redact_values": ("secret-key",), "capture": False}]


def test_get_capabilities_handles_invalid_credentials() -> None:
    with scripted_network([ScriptedResponse(status=401, json={"error": "unauthorized"})]):
        assert get_capabilities("bad-key") == (401, set())
