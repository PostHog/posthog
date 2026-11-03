from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.metorial import (
    MetorialSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.metorial import (
    DEFAULT_PAGE_SIZE,
    MetorialResumeConfig,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.source import MetorialSource

# A stand-in API key long enough to be caught by the transport's value-based redaction.
_SECRET_KEY = "metorial_sk_abcdef1234567890"


def _driver(api_key: str = "metorial_sk_x") -> SourceDriver:
    return SourceDriver(MetorialSource(), MetorialSourceConfig(api_key=api_key))


def _page(items: list[dict[str, Any]], *, has_more_after: bool = False) -> ScriptedResponse:
    return ScriptedResponse(json={"items": items, "pagination": {"has_more_after": has_more_after}})


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "ses_cursor", "ses_cursor"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        # The server filter rejects a +00:00 offset; the watermark must serialize with a Z suffix.
        result = _format_incremental_value(value)
        assert result == expected
        assert "+00:00" not in result


class TestResume:
    def test_resumes_from_saved_cursor(self) -> None:
        # A resumed run must continue from the persisted cursor, not restart the whole stream.
        result = _driver().run(
            "provider_runs",
            [_page([{"id": "prn_9"}])],
            resume_state=MetorialResumeConfig(after="prn_8"),
        )

        assert result.params("after") == ["prn_8"]
        assert [row["id"] for row in result.rows] == ["prn_9"]
        assert result.raised is None


class TestIncrementalFilter:
    def test_builds_gt_filter_for_chosen_field_on_every_page(self) -> None:
        # Dropping or misnaming this filter turns every "incremental" sync into a full refresh.
        result = _driver().run(
            "sessions",
            [_page([{"id": "ses_1"}], has_more_after=True), _page([{"id": "ses_2"}])],
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.params("updated_at[gt]") == ["2026-03-04T02:58:14.000Z"] * 2
        assert result.raised is None

    def test_first_sync_has_no_filter(self) -> None:
        # No watermark yet: sending an empty gt filter would 400 (or silently sync nothing).
        result = _driver().run("sessions", [_page([{"id": "ses_1"}])], incremental_field="updated_at")

        assert len(result.requests) == 1
        assert not any(key.endswith("[gt]") for key in result.requests[0].query)
        assert result.raised is None

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # providers exposes no server-side timestamp filter; it must not fabricate one.
        result = _driver().run(
            "providers",
            [_page([{"id": "pro_1"}])],
            incremental_field="created_at",
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.queries == [{"limit": (str(DEFAULT_PAGE_SIZE),), "order": ("asc",)}]
        assert result.raised is None


class TestSourceResponse:
    @parameterized.expand(
        [
            # Pagination is by record id (order=asc). `updated_at` is not monotonic in id order, so
            # those syncs must run "desc" (the pipeline then commits the watermark only after a full
            # run). An "asc" claim here lets an interrupted sync advance the watermark past rows it
            # hasn't fetched, silently losing them from the warehouse.
            ("sessions_default_updated_at", "sessions", None, "desc"),
            ("provider_runs_default_updated_at", "provider_runs", None, "desc"),
            ("provider_deployments_default_updated_at", "provider_deployments", None, "desc"),
            ("session_providers_default_updated_at", "session_providers", None, "desc"),
            ("integration_instances_default_updated_at", "integration_instances", None, "desc"),
            ("provider_versions_default_updated_at", "provider_versions", None, "desc"),
            # A user overriding sessions onto created_at makes per-batch checkpointing safe again.
            ("sessions_user_picks_created_at", "sessions", "created_at", "asc"),
            # created_at tracks id order, so append-only streams checkpoint safely per batch.
            ("session_messages_created_at", "session_messages", None, "asc"),
            ("tool_calls_created_at", "tool_calls", None, "asc"),
            # Full-refresh-only endpoint has no incremental field.
            ("providers_full_refresh", "providers", None, "asc"),
        ]
    )
    def test_sort_mode_matches_incremental_field(
        self, _name: str, endpoint: str, incremental_field: str | None, expected_sort_mode: str
    ) -> None:
        result = _driver().run(endpoint, [_page([])], incremental_field=incremental_field)

        assert result.raised is None
        assert result.response is not None
        assert result.response.sort_mode == expected_sort_mode
        assert result.response.primary_keys == ["id"]
        # Partition key must be the stable created_at, never updated_at (partitions would rewrite each sync).
        assert result.response.partition_keys == ["created_at"]


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    def test_4xx_raises_matchable_http_error_without_leaking_key(self, _name: str, status: int, reason: str) -> None:
        # The secret key must never reach the exception text (surfaced as the schema's latest_error
        # outside warehouse ACLs), but the stable `<status> Client Error: <reason> for url:
        # https://api.metorial.com...` prefix that get_non_retryable_errors() matches on must survive.
        result = _driver(_SECRET_KEY).run("sessions", [ScriptedResponse(status=status)])

        assert isinstance(result.raised, HTTPError)
        assert result.requests[0].headers["authorization"] == f"Bearer {_SECRET_KEY}"
        assert _SECRET_KEY in result.session_options[0]["redact_values"]
        message = str(result.raised)
        assert _SECRET_KEY not in message
        assert message.startswith(f"{status} Client Error: {reason} for url: https://api.metorial.com/sessions")

    @parameterized.expand([("server_error", 503), ("rate_limited", 429)])
    def test_transient_status_is_retried(self, _name: str, status: int) -> None:
        # 429/5xx are transient: back off and retry rather than failing the sync.
        headers = {"Retry-After": "1"} if status == 429 else {}
        result = _driver().run(
            "tool_calls",
            [ScriptedResponse(status=status, headers=headers), _page([{"id": "tcl_5"}])],
        )

        assert [row["id"] for row in result.rows] == ["tcl_5"]
        assert len(result.requests) == 2
        assert result.raised is None


class TestValidateCredentials:
    @parameterized.expand([("unauthorized", 401)])
    def test_invalid_key(self, _name: str, status: int) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("bad-key") is False

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/sessions"
        assert network.requests_log[0].param("limit") == "1"
