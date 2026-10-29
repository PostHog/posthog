from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailosaur import (
    MailosaurSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.mailosaur import (
    MailosaurResumeConfig,
    _format_received_after,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.source import MailosaurSource


def _driver() -> SourceDriver:
    return SourceDriver(MailosaurSource(), MailosaurSourceConfig(api_key="key"))


def _items(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"items": rows})


class TestFormatReceivedAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("none", None, None),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_received_after(value) == expected

    @parameterized.expand([("int_epoch", 1234567890), ("string", "not-a-date")])
    def test_unexpected_type_raises(self, _name: str, value: Any) -> None:
        # The messages cursor is a DateTime; an int/str would produce a receivedAfter Mailosaur
        # silently ignores (a full re-fetch), so we fail loud instead.
        with pytest.raises(TypeError):
            _format_received_after(value)


class TestMessagesFanOut:
    def test_injects_server_and_fans_out_over_servers(self) -> None:
        result = _driver().run(
            "messages",
            [
                _items([{"id": "s1"}, {"id": "s2"}]),
                _items([{"id": "m-s1"}]),
                _items([]),
                _items([{"id": "m-s2"}]),
                _items([]),
            ],
        )

        # Every message row must carry its parent server id — that's half of the (server, id)
        # primary key, and the summary payload omits it.
        assert result.raised is None
        assert result.rows == [
            {"id": "m-s1", "server": "s1"},
            {"id": "m-s2", "server": "s2"},
        ]
        assert result.paths == ["/api/servers", "/api/messages", "/api/messages", "/api/messages", "/api/messages"]
        assert result.params("server") == [None, "s1", "s1", "s2", "s2"]
        assert result.params("page") == [None, "0", "1", "0", "1"]

    def test_resumes_from_saved_fanout_state(self) -> None:
        # s1 already fully synced (its child path is in `completed`), so the resumed run must skip it.
        resume = MailosaurResumeConfig(
            paginator_state={"completed": ["/api/messages?server=s1"], "current": None, "child_state": None}
        )
        result = _driver().run(
            "messages",
            [_items([{"id": "s1"}, {"id": "s2"}]), _items([{"id": "m-s2"}]), _items([])],
            resume_state=resume,
        )

        assert result.raised is None
        assert result.paths == ["/api/servers", "/api/messages", "/api/messages"]
        assert result.params("server") == [None, "s2", "s2"]
        assert result.params("page") == [None, "0", "1"]
        assert result.rows == [{"id": "m-s2", "server": "s2"}]

    def test_incremental_passes_received_after(self) -> None:
        result = _driver().run(
            "messages",
            [_items([{"id": "s1"}]), _items([])],
            incremental_field="received",
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert result.raised is None
        message_requests = [request for request in result.requests if request.path == "/api/messages"]
        assert message_requests
        assert all(request.param("receivedAfter") == "2026-01-02T03:04:05Z" for request in message_requests)


class TestSimpleEndpoints:
    @parameterized.expand([("servers", "/api/servers"), ("usage_transactions", "/api/usage/transactions")])
    def test_single_request_yields_items(self, endpoint: str, expected_path: str) -> None:
        result = _driver().run(endpoint, [_items([{"id": "x"}])])

        assert result.raised is None
        assert result.rows == [{"id": "x"}]
        # A single-request full-refresh endpoint issues exactly one call.
        assert result.paths == [expected_path]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool, expected_error: str | None) -> None:
        answer = ScriptedResponse(status=status_code)
        script = always(answer) if status_code == 500 else [answer]
        with scripted_network(script) as network:
            ok, error = validate_credentials("key")

        assert ok is expected_ok
        assert error == expected_error
        assert {request.path for request in network.requests_log} == {"/api/servers"}

    def test_transport_error_is_not_validated(self) -> None:
        # A credential probe must never raise out of validate_credentials; a transport error just
        # means "not validated".
        with scripted_network(always(ConnectionError("boom"))) as network:
            ok, error = validate_credentials("key")

        assert ok is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/api/servers"}


class TestMailosaurSourceResponse:
    @parameterized.expand(
        [
            ("messages", ["server", "id"], "desc", ["received"]),
            ("servers", ["id"], "asc", None),
            ("usage_transactions", ["timestamp"], "asc", None),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_keys: list[str] | None
    ) -> None:
        result = _driver().run(endpoint, [_items([])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == primary_keys
        # sort_mode must match the real arrival order — messages come newest-first (desc), and a
        # wrong value corrupts the incremental watermark checkpoint.
        assert result.response.sort_mode == sort_mode
        assert result.response.partition_keys == partition_keys
