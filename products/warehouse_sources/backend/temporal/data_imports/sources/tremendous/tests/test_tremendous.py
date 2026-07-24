import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.settings import (
    ENDPOINTS,
    TREMENDOUS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.tremendous import (
    DEFAULT_PROBE_PATH,
    TremendousResumeConfig,
    _to_iso_datetime,
    base_url_for_environment,
    tremendous_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the tremendous module.
TREMENDOUS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.tremendous.make_tracked_session"
)

INVOICES_PAGE_SIZE = TREMENDOUS_ENDPOINTS["invoices"].page_size  # 10 — cheap full-page fixtures


def _response(items: list[dict[str, Any]], *, data_key: str = "orders") -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({data_key: items, "total_count": len(items)}).encode()
    return resp


def _raw_response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: TremendousResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(
    endpoint: str,
    manager: mock.MagicMock,
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    environment: str = "production",
) -> Any:
    return tremendous_source(
        api_key="tremendous-key",
        environment=environment,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        full_page = [{"id": f"i_{i}"} for i in range(INVOICES_PAGE_SIZE)]
        params = _wire(
            session, [_response(full_page, data_key="invoices"), _response([{"id": "i_last"}], data_key="invoices")]
        )

        manager = _make_manager()
        rows = _rows(_source("invoices", manager))

        assert [r["id"] for r in rows] == [*(f"i_{i}" for i in range(INVOICES_PAGE_SIZE)), "i_last"]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == INVOICES_PAGE_SIZE
        assert params[1]["offset"] == INVOICES_PAGE_SIZE
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == TremendousResumeConfig(offset=INVOICES_PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "A"}, {"id": "B"}])])

        manager = _make_manager()
        rows = _rows(_source("orders", manager))

        assert [r["id"] for r in rows] == ["A", "B"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_and_no_checkpoint(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source("orders", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "X"}])])

        manager = _make_manager(TremendousResumeConfig(offset=1000))
        _rows(_source("orders", manager))

        # The initial (offset=0) page must never be re-fetched on resume.
        assert [p["offset"] for p in params] == [1000]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_watermark_sent_as_created_at_gte_on_every_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        full_page = [{"id": f"o_{i}"} for i in range(TREMENDOUS_ENDPOINTS["orders"].page_size)]
        params = _wire(session, [_response(full_page), _response([])])

        _rows(
            _source(
                "orders",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            )
        )

        assert len(params) == 2
        assert all(p["created_at[gte]"] == "2026-01-02T03:04:05+00:00" for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sends_no_created_at_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "A"}])])

        _rows(_source("orders", _make_manager()))

        assert all("created_at[gte]" not in p for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoint_fetches_once_without_offset_limit(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "M1"}, {"id": "M2"}], data_key="members")])

        manager = _make_manager()
        rows = _rows(_source("members", manager))

        assert [r["id"] for r in rows] == ["M1", "M2"]
        assert session.send.call_count == 1
        # A single-page endpoint sends no offset/limit pagination params.
        assert "offset" not in params[0] and "limit" not in params[0]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pins_redirects_off(self, MockSession: mock.MagicMock) -> None:
        # Redirect-following would replay the Bearer key to whatever host Tremendous redirects to.
        session = MockSession.return_value
        _wire(session, [_response([{"id": "A"}])])

        _rows(_source("orders", _make_manager()))

        assert session.send.call_args.kwargs["allow_redirects"] is False

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_payload_is_retryable(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        # A 200 whose body isn't the expected {data_key: [...]} shape is retried, then re-raised.
        session = MockSession.return_value
        _wire(session, [_raw_response({"total_count": 0})] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("orders", _make_manager()))

    @parameterized.expand(
        [
            ("non_dict_body", [{"id": "A"}]),
            ("missing_data_key", {"total_count": 0}),
            ("data_key_not_a_list", {"orders": {"id": "A"}}),
        ]
    )
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_payload_shapes_are_retryable(
        self, _name: str, body: Any, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_raw_response(body)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("orders", _make_manager()))


class TestHelpers:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05+00:00"),
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05+00:00"),
            ("date", date(2026, 1, 2), "2026-01-02T00:00:00+00:00"),
            ("string_passthrough", "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z"),
            ("none", None, None),
            ("empty_string", "", None),
        ]
    )
    def test_to_iso_datetime(self, _name: str, value: Any, expected: str | None) -> None:
        assert _to_iso_datetime(value) == expected

    @parameterized.expand(
        [
            ("production", "https://www.tremendous.com/api/v2"),
            ("sandbox", "https://testflight.tremendous.com/api/v2"),
            # Unknown values fall back to production rather than building a bad URL.
            ("bogus", "https://www.tremendous.com/api/v2"),
        ]
    )
    def test_base_url_for_environment(self, environment: str, expected: str) -> None:
        assert base_url_for_environment(environment) == expected


class TestValidateCredentials:
    @staticmethod
    def _session(response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Tremendous API key (check that it matches the selected environment)"),
            ("forbidden", 403, False, "Invalid Tremendous API key (check that it matches the selected environment)"),
            ("server_error", 500, False, "Tremendous returned HTTP 500"),
        ]
    )
    @mock.patch(TREMENDOUS_SESSION_PATCH)
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        mock_session.return_value = self._session(mock.MagicMock(status_code=status))
        assert validate_credentials("tremendous-key", "production") == (expected_valid, expected_message)

    @mock.patch(TREMENDOUS_SESSION_PATCH)
    def test_connection_error_is_not_validated(self, mock_session: mock.MagicMock) -> None:
        # A credential probe must never raise; a transport failure means "not validated".
        mock_session.return_value = self._session(ConnectionError("boom"))
        assert validate_credentials("tremendous-key", "production") == (False, "Could not validate Tremendous API key")

    @mock.patch(TREMENDOUS_SESSION_PATCH)
    def test_pins_redirects_off(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value = self._session(mock.MagicMock(status_code=200))
        validate_credentials("tremendous-key", "production")
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    @mock.patch(TREMENDOUS_SESSION_PATCH)
    def test_probe_targets_selected_environment(self, mock_session: mock.MagicMock) -> None:
        session = self._session(mock.MagicMock(status_code=200))
        mock_session.return_value = session
        validate_credentials("tremendous-key", "sandbox")
        url = session.get.call_args.args[0]
        assert url == f"https://testflight.tremendous.com/api/v2{DEFAULT_PROBE_PATH}"


class TestTremendousSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Tremendous lists are creation-date DESC; declaring asc would corrupt the incremental watermark.
        assert response.sort_mode == "desc"
        if TREMENDOUS_ENDPOINTS[endpoint].partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["created_at"]
        else:
            assert response.partition_mode is None

    def test_partition_keys_are_stable_creation_timestamps(self) -> None:
        # Partition keys must never be updated_at-style fields, which rewrite partitions every sync.
        assert {c.partition_key for c in TREMENDOUS_ENDPOINTS.values()} == {"created_at", None}
