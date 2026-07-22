import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge import (
    RechargeResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    recharge_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.settings import RECHARGE_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the recharge module.
RECHARGE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _page(endpoint: str, items: list[dict[str, Any]], next_cursor: str | None) -> Response:
    return _response({endpoint: items, "next_cursor": next_cursor})


def _make_manager(resume_state: RechargeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
            ("string_passthrough", "2026-03-04T00:00:00", "2026-03-04T00:00:00"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected

    def test_no_offset_suffix(self) -> None:
        # Recharge rejects timezone offsets in `*_min` filters.
        assert "+00:00" not in _format_incremental_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestBuildInitialParams:
    def test_incremental_on_updated_at_sets_min_and_sort(self) -> None:
        params = _build_initial_params(
            RECHARGE_ENDPOINTS["customers"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params["updated_at_min"] == "2026-03-04T02:58:14"
        assert params["sort_by"] == "updated_at-asc"
        assert params["limit"] == 250

    def test_incremental_on_created_at_uses_created_field(self) -> None:
        params = _build_initial_params(
            RECHARGE_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert params["created_at_min"] == "2026-01-01T00:00:00"
        assert params["sort_by"] == "created_at-asc"
        assert "updated_at_min" not in params

    def test_full_refresh_sorts_by_stable_id(self) -> None:
        params = _build_initial_params(
            RECHARGE_ENDPOINTS["customers"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params["sort_by"] == "id-asc"
        assert not any(k.endswith("_min") for k in params)

    @parameterized.expand(
        [
            ("default_endpoint_uses_max_page_size", "customers", 250),
            ("payment_methods_uses_smaller_page_size", "payment_methods", 50),
        ]
    )
    def test_page_size_is_per_endpoint(self, _name: str, endpoint: str, expected_limit: int) -> None:
        # `payment_methods` pages are too slow to generate within the read timeout
        # at the 250 max, so it requests smaller pages.
        params = _build_initial_params(
            RECHARGE_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params["limit"] == expected_limit

    @parameterized.expand(
        [
            # `collections` is full-refresh but still sortable -> keeps `id-asc`.
            ("collections", {"limit": 250, "sort_by": "id-asc"}),
            # `/products` on the 2021-11 API rejects `sort_by` outright -> limit only.
            ("products", {"limit": 250}),
        ]
    )
    def test_full_refresh_endpoint_ignores_incremental_inputs(self, endpoint: str, expected: dict) -> None:
        # Full-refresh endpoints must never emit a `*_min` filter even when the user
        # supplies incremental inputs; products additionally omits `sort_by`.
        params = _build_initial_params(
            RECHARGE_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params == expected
        assert not any(k.endswith("_min") for k in params)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("server_error", 500, False),
            ("forbidden", 403, False),
        ]
    )
    @mock.patch(RECHARGE_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status_code: int, expected_ok: bool, mock_session: mock.MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        ok, error = validate_credentials("token")
        assert ok is expected_ok
        if not expected_ok:
            assert error is not None

    @mock.patch(RECHARGE_SESSION_PATCH)
    def test_network_error_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, error = validate_credentials("token")
        assert ok is False
        assert error is not None

    @mock.patch(RECHARGE_SESSION_PATCH)
    def test_token_is_redacted_from_captured_samples(self, mock_session: mock.MagicMock) -> None:
        # The `X-Recharge-Access-Token` header isn't in the shared auth-header
        # denylist, so the token must be passed as a `redact_values` literal to
        # keep it out of captured HTTP samples.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret-token")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret-token",)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_no_cursor_and_saves_state_after_yield(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("customers", [{"id": 1}], "cursor-2"), _page("customers", [{"id": 2}], None)])

        manager = _make_manager()
        rows = _rows(recharge_source("token", "customers", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"id": 1}, {"id": 2}]
        # State saved once — only when there's a next cursor to resume from.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == RechargeResumeConfig(endpoint="customers", cursor="cursor-2")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_extracts_rows_under_endpoint_key(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("orders", [{"id": 7}, {"id": 8}], None)])

        rows = _rows(recharge_source("t", "orders", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert rows == [{"id": 7}, {"id": 8}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_resource_key_yields_no_rows(self, MockSession) -> None:
        # A body without the resource key (and only cursor keys) is a zero-row page,
        # not an error — the old client returned [] here rather than raising.
        session = MockSession.return_value
        _wire(session, [_response({"next_cursor": None})])

        rows = _rows(recharge_source("t", "customers", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_token_is_redacted_from_captured_samples(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("customers", [{"id": 1}], None)])

        _rows(
            recharge_source(
                "secret-token", "customers", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )
        assert MockSession.call_args.kwargs["redact_values"] == ("secret-token",)

    @parameterized.expand(
        [
            ("payment_methods_uses_smaller_limit", "payment_methods", 50),
            ("customers_use_default_limit", "customers", 250),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_pages_use_per_endpoint_limit_and_drop_filters(
        self, _name: str, endpoint: str, expected_limit: int, MockSession
    ) -> None:
        # Both the first page and cursor pages carry the per-endpoint limit; the
        # cursor page sends ONLY cursor + limit (Recharge 422s if the original
        # sort/filter params are re-sent alongside a cursor).
        session = MockSession.return_value
        params = _wire(session, [_page(endpoint, [{"id": 1}], "cursor-2"), _page(endpoint, [{"id": 2}], None)])

        _rows(recharge_source("t", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        assert params[0]["limit"] == expected_limit
        assert params[0]["sort_by"] == "id-asc"
        assert params[1] == {"cursor": "cursor-2", "limit": expected_limit}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_products_request_omits_sort_by(self, MockSession) -> None:
        # Regression: the 2021-11 `/products` endpoint 422s on `sort_by`, so the
        # initial request must send only `limit` (no sort, no timestamp filter).
        session = MockSession.return_value
        params = _wire(session, [_page("products", [{"id": 1}], None)])

        _rows(recharge_source("t", "products", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        assert params[0] == {"limit": 250}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor_when_endpoint_matches(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("customers", [{"id": 9}], None)])

        manager = _make_manager(RechargeResumeConfig(endpoint="customers", cursor="saved-cursor"))
        _rows(recharge_source("t", "customers", team_id=1, job_id="j", resumable_source_manager=manager))

        # When following a cursor we only send cursor + limit, no sort/filters.
        assert params[0] == {"cursor": "saved-cursor", "limit": 250}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_ignores_resume_state_from_different_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("orders", [{"id": 1}], None)])

        manager = _make_manager(RechargeResumeConfig(endpoint="customers", cursor="saved-cursor"))
        _rows(recharge_source("t", "orders", team_id=1, job_id="j", resumable_source_manager=manager))

        assert "cursor" not in params[0]
        assert params[0]["sort_by"] == "id-asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_first_page_sends_min_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("customers", [{"id": 1}], None)])

        _rows(
            recharge_source(
                "t",
                "customers",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        assert params[0]["updated_at_min"] == "2026-01-01T00:00:00"
        assert params[0]["sort_by"] == "updated_at-asc"


class TestRechargeSource:
    @parameterized.expand([(name,) for name in RECHARGE_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = recharge_source(
            "token",
            endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
