import json
import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet import (
    HatchetConnection,
    HatchetHostNotAllowedError,
    HatchetResumeConfig,
    HatchetTokenError,
    _build_initial_params,
    _normalize_row,
    _resolve_since,
    get_rows,
    resolve_connection,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.settings import HATCHET_ENDPOINTS

logger = structlog.get_logger()


def _make_token(claims: dict[str, Any]) -> str:
    """Build a JWT-shaped token whose (unverified) payload carries the given claims."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.signature"


class FakeManager:
    """Stand-in for ResumableSourceManager that records saved state and can replay a resume value."""

    def __init__(self, resume: HatchetResumeConfig | None = None):
        self._resume = resume
        self.saved: list[HatchetResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume is not None

    def load_state(self) -> HatchetResumeConfig | None:
        return self._resume

    def save_state(self, data: HatchetResumeConfig) -> None:
        self.saved.append(data)


class TestResolveConnection:
    def test_derives_tenant_and_host_from_token_claims(self):
        token = _make_token({"sub": "tenant-abc", "server_url": "https://my.hatchet.example/"})

        connection = resolve_connection(token)

        assert connection.tenant_id == "tenant-abc"
        # Trailing slash trimmed so path concatenation doesn't double up.
        assert connection.base_url == "https://my.hatchet.example"

    def test_explicit_overrides_win_over_token_claims(self):
        token = _make_token({"sub": "tenant-abc", "server_url": "https://cloud.example"})

        connection = resolve_connection(token, host="https://self-hosted.example/", tenant_id="tenant-override")

        assert connection.tenant_id == "tenant-override"
        assert connection.base_url == "https://self-hosted.example"

    def test_falls_back_to_cloud_host_when_token_has_no_server_url(self):
        token = _make_token({"sub": "tenant-abc"})

        connection = resolve_connection(token)

        assert connection.base_url == "https://cloud.onhatchet.run"

    @pytest.mark.parametrize("token", ["not-a-jwt", "only.two", ""])
    def test_malformed_token_raises_token_error(self, token):
        with pytest.raises(HatchetTokenError):
            resolve_connection(token)

    def test_missing_tenant_raises_token_error(self):
        token = _make_token({"server_url": "https://cloud.example"})

        with pytest.raises(HatchetTokenError):
            resolve_connection(token)


class TestResolveSince:
    def test_incremental_with_watermark_subtracts_lookback(self):
        config = HATCHET_ENDPOINTS["workflow_runs"]
        watermark = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

        since = _resolve_since(config, should_use_incremental_field=True, db_incremental_field_last_value=watermark)

        lookback = config.incremental_lookback
        assert lookback is not None
        assert since == watermark - lookback

    def test_future_watermark_capped_to_now(self):
        config = HATCHET_ENDPOINTS["workflow_runs"]
        future = datetime.now(UTC) + timedelta(days=30)

        since = _resolve_since(config, should_use_incremental_field=True, db_incremental_field_last_value=future)

        # A future cursor would make the API return nothing, so it's capped at ~now (then shifted back).
        assert since is not None and since <= datetime.now(UTC)

    def test_first_incremental_sync_floors_to_lookback_days(self):
        config = HATCHET_ENDPOINTS["workflow_runs"]

        since = _resolve_since(config, should_use_incremental_field=True, db_incremental_field_last_value=None)

        assert since is not None
        delta_days = (datetime.now(UTC) - since).days
        assert delta_days == pytest.approx(config.default_lookback_days, abs=1)

    def test_full_refresh_uses_far_past_floor_when_since_required(self):
        config = HATCHET_ENDPOINTS["workflow_runs"]

        since = _resolve_since(config, should_use_incremental_field=False, db_incremental_field_last_value=None)

        # workflow-runs requires `since` even on full refresh, so a far-past floor is sent.
        assert since is not None and since.year <= 2020

    def test_full_refresh_without_required_since_sends_nothing(self):
        config = HATCHET_ENDPOINTS["event_keys"]

        since = _resolve_since(config, should_use_incremental_field=False, db_incremental_field_last_value=None)

        assert since is None


class TestBuildInitialParams:
    def test_workflow_runs_carries_required_static_params(self):
        params = _build_initial_params(
            HATCHET_ENDPOINTS["workflow_runs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )

        # only_tasks and include_payloads are required/expected by the endpoint and must always be sent.
        assert params["only_tasks"] == "false"
        assert params["include_payloads"] == "true"
        assert params["limit"] == 100
        assert "since" in params

    def test_tasks_endpoint_sets_only_tasks_true(self):
        params = _build_initial_params(
            HATCHET_ENDPOINTS["tasks"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )

        assert params["only_tasks"] == "true"

    def test_event_keys_has_no_time_window(self):
        params = _build_initial_params(
            HATCHET_ENDPOINTS["event_keys"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )

        assert "since" not in params


class TestNormalizeRow:
    def test_flattens_metadata_envelope(self):
        row = _normalize_row(
            {
                "metadata": {"id": "run-1", "createdAt": "2026-06-01T00:00:00Z", "updatedAt": "2026-06-02T00:00:00Z"},
                "status": "COMPLETED",
            }
        )

        assert row["id"] == "run-1"
        assert row["created_at"] == "2026-06-01T00:00:00Z"
        assert row["updated_at"] == "2026-06-02T00:00:00Z"
        assert row["status"] == "COMPLETED"
        assert "metadata" not in row

    def test_wraps_bare_event_key_string(self):
        assert _normalize_row("user:signed_up") == {"key": "user:signed_up"}

    def test_leaves_row_without_metadata_untouched(self):
        assert _normalize_row({"key": "abc"}) == {"key": "abc"}


def _collect(tables) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in tables:
        rows.extend(table.to_pylist())
    return rows


def _row(row_id: str) -> dict[str, Any]:
    return {"metadata": {"id": row_id, "createdAt": "2026-06-01T00:00:00Z", "updatedAt": "2026-06-01T00:00:00Z"}}


class TestGetRows:
    def _connection(self) -> HatchetConnection:
        return HatchetConnection(base_url="https://cloud.example", tenant_id="tenant-1")

    def test_single_short_page_terminates_after_one_fetch(self):
        manager = FakeManager()
        page = {"rows": [_row("a"), _row("b")], "pagination": {"current_page": 1, "num_pages": 1}}

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._fetch_page",
            return_value=page,
        ) as fetch:
            rows = _collect(
                get_rows("tok", self._connection(), "workflow_runs", logger, manager, team_id=1)  # type: ignore[arg-type]
            )

        assert fetch.call_count == 1
        assert [r["id"] for r in rows] == ["a", "b"]
        # Last page → no resume state persisted.
        assert manager.saved == []

    def test_pagination_walks_offsets_until_num_pages_reached(self):
        manager = FakeManager()
        full_page = [_row(f"p1-{i}") for i in range(100)]
        second_page = [_row(f"p2-{i}") for i in range(100)]
        pages = [
            {"rows": full_page, "pagination": {"current_page": 1, "num_pages": 2}},
            {"rows": second_page, "pagination": {"current_page": 2, "num_pages": 2}},
        ]
        captured_urls: list[str] = []

        def fake_fetch(session, url, headers, log):
            captured_urls.append(url)
            return pages[len(captured_urls) - 1]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._fetch_page",
            side_effect=fake_fetch,
        ):
            rows = _collect(
                get_rows("tok", self._connection(), "workflow_runs", logger, manager, team_id=1)  # type: ignore[arg-type]
            )

        assert len(rows) == 200
        # Second request advances the offset by the page size.
        assert "offset=0" in captured_urls[0]
        assert "offset=100" in captured_urls[1]

    def test_resume_starts_from_saved_offset_and_pins_since(self):
        manager = FakeManager(resume=HatchetResumeConfig(offset=100, since="2026-01-01T00:00:00.000000Z"))
        captured_urls: list[str] = []

        def fake_fetch(session, url, headers, log):
            captured_urls.append(url)
            return {"rows": [_row("x")], "pagination": {"current_page": 2, "num_pages": 2}}

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._fetch_page",
            side_effect=fake_fetch,
        ):
            _collect(get_rows("tok", self._connection(), "workflow_runs", logger, manager, 1, True, None))  # type: ignore[arg-type]

        assert "offset=100" in captured_urls[0]
        # The window the interrupted run started on is replayed, not recomputed from a new watermark.
        assert "since=2026-01-01T00%3A00%3A00.000000Z" in captured_urls[0]

    def test_syncs_bare_top_level_array_response(self):
        # event_keys returns a top-level JSON array, not a `{"rows": [...]}` envelope; it must still
        # sync instead of silently loading zero rows.
        manager = FakeManager()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._fetch_page",
            return_value=["user:signed_up", "billing:charged"],
        ):
            rows = _collect(
                get_rows("tok", self._connection(), "event_keys", logger, manager, team_id=1)  # type: ignore[arg-type]
            )

        assert rows == [{"key": "user:signed_up"}, {"key": "billing:charged"}]

    def test_unsafe_host_raises_before_any_fetch(self):
        manager = FakeManager()

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._is_host_safe",
                return_value=(False, "Hosts with internal IP addresses are not allowed"),
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._fetch_page",
            ) as fetch,
        ):
            with pytest.raises(HatchetHostNotAllowedError):
                _collect(get_rows("tok", self._connection(), "workflow_runs", logger, manager, team_id=99))  # type: ignore[arg-type]

        fetch.assert_not_called()

    def test_plaintext_http_host_raises_on_cloud(self):
        # On cloud the bearer token must never go over plaintext http, even when the host passes the
        # SSRF check.
        manager = FakeManager()
        connection = HatchetConnection(base_url="http://cloud.example", tenant_id="tenant-1")

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._is_host_safe",
                return_value=(True, None),
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet.is_cloud",
                return_value=True,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._fetch_page",
            ) as fetch,
        ):
            with pytest.raises(HatchetHostNotAllowedError):
                _collect(get_rows("tok", connection, "workflow_runs", logger, manager, team_id=1))  # type: ignore[arg-type]

        fetch.assert_not_called()

    def test_session_disables_redirects_and_redacts_token(self):
        # The bearer token is sent to a user-controlled host, so the session must never follow a
        # redirect off it and must redact the token from captured samples/logs. Response bodies
        # carry opaque workflow payloads, so they must also be excluded from HTTP sample capture.
        manager = FakeManager()
        page = {"rows": [_row("a")], "pagination": {"current_page": 1, "num_pages": 1}}

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet.make_tracked_session"
            ) as session,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._fetch_page",
                return_value=page,
            ),
        ):
            _collect(get_rows("tok", self._connection(), "workflow_runs", logger, manager, team_id=1))  # type: ignore[arg-type]

        assert session.call_args.kwargs["allow_redirects"] is False
        assert session.call_args.kwargs["redact_values"] == ("tok",)
        assert session.call_args.kwargs["capture"] is False


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid",
        [(200, True), (401, False), (403, False), (404, False), (500, False)],
    )
    def test_status_mapping(self, status_code, expected_valid):
        token = _make_token({"sub": "tenant-1", "server_url": "https://cloud.example"})
        response = mock.MagicMock()
        response.status_code = status_code

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet.make_tracked_session"
        ) as session:
            session.return_value.get.return_value = response
            valid, message = validate_credentials(token, None, None)

        assert valid is expected_valid
        if not expected_valid:
            assert message

    def test_undecodable_token_fails_without_network_call(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet.make_tracked_session"
        ) as session:
            valid, message = validate_credentials("garbage", None, None)

        assert valid is False
        assert message
        session.assert_not_called()

    def test_unsafe_host_fails_before_network_call(self):
        # A host resolving to an internal address must be rejected before the token is ever sent.
        token = _make_token({"sub": "tenant-1", "server_url": "https://internal.example"})

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._is_host_safe",
                return_value=(False, "Hosts with internal IP addresses are not allowed"),
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet.make_tracked_session"
            ) as session,
        ):
            valid, message = validate_credentials(token, None, None, team_id=99)

        assert valid is False
        assert message
        session.assert_not_called()

    def test_plaintext_http_host_fails_on_cloud(self):
        # On cloud, a plaintext http host must be rejected before the token is sent — even when the
        # host itself passes the SSRF check.
        token = _make_token({"sub": "tenant-1", "server_url": "http://cloud.example"})

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._is_host_safe",
                return_value=(True, None),
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet.is_cloud",
                return_value=True,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet.make_tracked_session"
            ) as session,
        ):
            valid, message = validate_credentials(token, None, None, team_id=99)

        assert valid is False
        assert message
        session.assert_not_called()
