import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.settings import VEEQO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.veeqo import (
    VeeqoPaginator,
    VeeqoResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    validate_credentials,
    veeqo_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the veeqo module.
VEEQO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.veeqo.make_tracked_session"
)


def _response(body: Any, status_code: int = 200, headers: dict[str, str] | None = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers.update(headers or {})
    return resp


def _make_manager(resume_state: VeeqoResumeConfig | None = None) -> mock.MagicMock:
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


def _full_page(page_size: int = 100) -> list[dict[str, Any]]:
    return [{"id": i} for i in range(page_size)]


class TestVeeqoPaginator:
    def test_empty_page_stops(self) -> None:
        paginator = VeeqoPaginator(page_size=100)
        paginator.update_state(_response([]), [])
        assert paginator.has_next_page is False

    def test_malformed_total_pages_header_falls_back_to_page_size_check(self) -> None:
        paginator = VeeqoPaginator(page_size=100)
        paginator.update_state(_response(_full_page(), headers={"X-Total-Pages-Count": "unknown"}), _full_page())
        # A full page with an unparseable header keeps paginating rather than crashing.
        assert paginator.has_next_page is True


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", "updated_at", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04 02:58:14"),
            ("naive_datetime", "updated_at", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04 02:58:14"),
            (
                "non_utc_datetime_normalized",
                "created_at",
                datetime(2026, 3, 4, 4, 58, 14, tzinfo=timezone(timedelta(hours=2))),
                "2026-03-04 02:58:14",
            ),
            ("date_value", "created_at", date(2026, 3, 4), "2026-03-04 00:00:00"),
            ("string_passthrough", "updated_at", "2026-03-04 00:00:00", "2026-03-04 00:00:00"),
            ("id_as_int", "id", 12345, 12345),
            ("id_string_coerced", "id", "12345", 12345),
        ]
    )
    def test_format_incremental_value(self, _name: str, field: str, value: object, expected: object) -> None:
        assert _format_incremental_value(field, value) == expected


class TestBuildInitialParams:
    @parameterized.expand(
        [
            ("updated_at", "updated_at_min", "2026-03-04 02:58:14"),
            ("created_at", "created_at_min", "2026-03-04 02:58:14"),
        ]
    )
    def test_incremental_maps_user_field_to_documented_param(
        self, incremental_field: str, expected_param: str, expected_value: str
    ) -> None:
        params = _build_initial_params(
            VEEQO_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field=incremental_field,
        )
        assert params[expected_param] == expected_value
        assert params["page_size"] == 100


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    @mock.patch(VEEQO_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status_code: int, expected_ok: bool, mock_session: mock.MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        ok, error = validate_credentials("key")
        assert ok is expected_ok
        if not expected_ok:
            assert error is not None

    @mock.patch(VEEQO_SESSION_PATCH)
    def test_network_error_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, error = validate_credentials("key")
        assert ok is False
        assert error is not None

    @mock.patch(VEEQO_SESSION_PATCH)
    def test_key_is_redacted_from_captured_samples(self, mock_session: mock.MagicMock) -> None:
        # `x-api-key` isn't in the shared auth-header denylist, so the key must be
        # passed as a `redact_values` literal to keep it out of captured HTTP samples.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret-key")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_saves_state_after_each_non_terminal_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(_full_page(), headers={"X-Total-Pages-Count": "2"}),
                _response([{"id": 900}], headers={"X-Total-Pages-Count": "2"}),
            ],
        )

        manager = _make_manager()
        rows = _rows(veeqo_source("key", "orders", team_id=1, job_id="j", resumable_source_manager=manager))

        assert len(rows) == 101
        assert [p["page"] for p in params] == [1, 2]
        assert params[0]["page_size"] == 100
        # State saved once — only while a next page remains to resume from.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == VeeqoResumeConfig(endpoint="orders", page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page_when_endpoint_matches(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}])])

        manager = _make_manager(VeeqoResumeConfig(endpoint="orders", page=7))
        _rows(veeqo_source("key", "orders", team_id=1, job_id="j", resumable_source_manager=manager))

        assert params[0]["page"] == 7

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_first_page_sends_min_filter_on_every_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(_full_page(), headers={"X-Total-Pages-Count": "2"}),
                _response([{"id": 900}]),
            ],
        )

        _rows(
            veeqo_source(
                "key",
                "orders",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        # The filter must stay on every page — the paginator only advances `page`.
        assert all(p["updated_at_min"] == "2026-01-01 00:00:00" for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redirects_are_refused(self, MockSession) -> None:
        # requests preserves the custom x-api-key header across redirects, so a
        # redirect response could replay the full-account key to another host —
        # every sync request must be sent with redirects disabled.
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        _rows(veeqo_source("key", "orders", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        assert session.send.call_args.kwargs["allow_redirects"] is False

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_fails_loud(self, MockSession) -> None:
        # Veeqo list responses are documented as bare arrays; a wrapper object on a
        # 200 means the response shape changed and must not sync as a single row.
        session = MockSession.return_value
        _wire(session, [_response({"orders": [{"id": 1}]})])

        with pytest.raises(ValueError, match="list"):
            _rows(veeqo_source("key", "orders", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_is_redacted_from_captured_samples(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        _rows(veeqo_source("secret-key", "orders", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        # The framework api_key auth exposes the key via secret_values(), which the
        # tracked session receives as redact_values.
        assert "secret-key" in MockSession.call_args.kwargs["redact_values"]


class TestVeeqoSourceResponse:
    @parameterized.expand([(name,) for name in VEEQO_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = veeqo_source(
            "key",
            endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        config = VEEQO_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Veeqo documents no list ordering, so the watermark must only commit after
        # a successful sync (desc semantics) — asc would checkpoint ≈now mid-sync.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
