import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless import (
    GoCardlessResumeConfig,
    _base_url,
    _format_created_at,
    gocardless_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.settings import (
    ENDPOINTS,
    GOCARDLESS_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the gocardless module.
GOCARDLESS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless.make_tracked_session"
)


def _status_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = b'{"error": {"code": %d}}' % status_code
    return resp


def _response(data_key: str, items: list[dict[str, Any]], after: str | None = None) -> Response:
    body = {data_key: items, "meta": {"cursors": {"before": None, "after": after}, "limit": 500}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: GoCardlessResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session, capturing each request's params and URL at prepare time.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy per page.
    The returned prepared object exposes a real ``.url`` so the client's host-pinning check passes.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        prepared = mock.MagicMock()
        prepared.url = request.url
        prepared.is_redirect = False
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(
    session: mock.MagicMock,
    environment: str,
    endpoint: str,
    manager: mock.MagicMock,
    db_incremental_field_last_value: Any = None,
) -> list[dict[str, Any]]:
    return _rows(
        gocardless_source(
            environment=environment,
            access_token="token",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
    )


class TestBaseUrl:
    @pytest.mark.parametrize(
        "environment, expected",
        [
            ("live", "https://api.gocardless.com"),
            ("sandbox", "https://api-sandbox.gocardless.com"),
        ],
    )
    def test_known_environment_returns_host(self, environment, expected):
        assert _base_url(environment) == expected

    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil.example.com")


class TestFormatCreatedAt:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, 123000, tzinfo=UTC), "2024-01-02T03:04:05.123Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05.000Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00.000Z"),
            ("2024-01-02T03:04:05.000Z", "2024-01-02T03:04:05.000Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_created_at(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(GOCARDLESS_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("live", "token") is expected

    @mock.patch(GOCARDLESS_SESSION_PATCH)
    def test_validate_credentials_rejects_bad_environment_without_request(self, mock_session):
        assert validate_credentials("evil", "token") is False
        mock_session.return_value.get.assert_not_called()

    @mock.patch(GOCARDLESS_SESSION_PATCH)
    def test_validate_credentials_swallows_transport_errors(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("live", "token") is False


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_meta_cursors(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(
            session,
            [
                _response("payments", [{"id": "PM1"}], after="PM1"),
                _response("payments", [{"id": "PM2"}], after=None),
            ],
        )

        manager = _make_manager()
        rows = _run(session, "live", "payments", manager)

        assert [r["id"] for r in rows] == ["PM1", "PM2"]
        assert params[0]["limit"] == 500
        assert "after" not in params[0]
        assert params[1]["after"] == "PM1"
        # Checkpoint saved after the first page (points at the next cursor); the null cursor ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == GoCardlessResumeConfig(after="PM1")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_requests_carry_version_header(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response("payments", [{"id": "PM1"}])])

        _run(session, "live", "payments", _make_manager())

        assert session.headers.get("GoCardless-Version") == "2015-07-06"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sandbox_uses_sandbox_host(self, MockSession):
        session = MockSession.return_value
        _, urls = _wire(session, [_response("payments", [{"id": "PM1"}])])

        _run(session, "sandbox", "payments", _make_manager())

        assert urlparse(urls[0]).netloc == "api-sandbox.gocardless.com"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_live_uses_live_host(self, MockSession):
        session = MockSession.return_value
        _, urls = _wire(session, [_response("payments", [{"id": "PM1"}])])

        _run(session, "live", "payments", _make_manager())

        assert urlparse(urls[0]).netloc == "api.gocardless.com"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_includes_filter(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(session, [_response("events", [{"id": "EV1"}])])

        _run(
            session,
            "live",
            "events",
            _make_manager(),
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert params[0]["created_at[gte]"] == "2024-01-02T00:00:00.000Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_omits_filter(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(session, [_response("events", [{"id": "EV1"}])])

        _run(session, "live", "events", _make_manager())

        assert "created_at[gte]" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_incremental_endpoint_ignores_watermark(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(session, [_response("payments", [{"id": "PM1"}])])

        _run(
            session,
            "live",
            "payments",
            _make_manager(),
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert "created_at[gte]" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(session, [_response("payments", [{"id": "PM9"}])])

        manager = _make_manager(GoCardlessResumeConfig(after="PM_RESUME"))
        _run(session, "live", "payments", manager)

        assert params[0]["after"] == "PM_RESUME"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_cursor_stops(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response("payments", [], after="PM_LOOP")])

        manager = _make_manager()
        rows = _run(session, "live", "payments", manager)

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestFanout:
    @pytest.mark.parametrize(
        "endpoint, parent_key, parent_id, resolve_param, injected_key",
        [
            ("payout_items", "payouts", "PO1", "payout", "payout_id"),
            ("balances", "creditors", "CR1", "creditor", "creditor_id"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_child_is_fetched_per_parent_with_parent_id_injected(
        self, MockSession, endpoint, parent_key, parent_id, resolve_param, injected_key
    ):
        session = MockSession.return_value
        params, urls = _wire(
            session,
            [
                _response(parent_key, [{"id": parent_id}]),
                _response(endpoint, [{"type": "a", "amount": "1"}], after="X1"),
                _response(endpoint, [{"type": "b", "amount": "2"}]),
            ],
        )

        rows = _run(session, "live", endpoint, _make_manager())

        assert urlparse(urls[1]).path == f"/{endpoint}"
        assert parse_qs(urlparse(urls[1]).query) == {resolve_param: [parent_id]}
        assert params[2]["after"] == "X1"
        assert [r["type"] for r in rows] == ["a", "b"]
        assert all(r[injected_key] == parent_id for r in rows)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_payout_items_skips_payouts_past_the_retention_window(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(
            session,
            [
                _response("payouts", [{"id": "PO_OLD"}, {"id": "PO_NEW"}]),
                _status_response(410),
                _response("payout_items", [{"type": "payment_paid_out", "amount": "100"}]),
            ],
        )

        rows = _run(session, "live", "payout_items", _make_manager())

        assert [r["payout_id"] for r in rows] == ["PO_NEW"]
        assert params[0]["created_at[gte]"] > _format_created_at(datetime.now(UTC) - timedelta(days=187))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_balances_lists_every_creditor(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(session, [_response("creditors", [{"id": "CR1"}]), _response("balances", [])])

        _run(session, "live", "balances", _make_manager())

        assert "created_at[gte]" not in params[0]


class TestGoCardlessSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = GOCARDLESS_ENDPOINTS[endpoint]
        response = gocardless_source(
            environment="live",
            access_token="token",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        assert response.name == endpoint
        if config.primary_key is None:
            assert response.primary_keys is None
            assert response.partition_keys is None
            return
        assert response.primary_keys == [config.primary_key]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        # Lists are reverse-chronological; only the incremental events stream
        # declares desc so the pipeline defers its watermark commit.
        if config.incremental_fields:
            assert response.sort_mode == "desc"
        else:
            assert response.sort_mode == "asc"

    @pytest.mark.parametrize("config", list(GOCARDLESS_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        assert config.partition_key in ("created_at", None)
