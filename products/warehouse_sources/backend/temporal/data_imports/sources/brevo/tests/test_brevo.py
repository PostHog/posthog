import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.brevo import (
    BREVO_BASE_URL,
    BrevoResumeConfig,
    _build_base_params,
    _format_datetime,
    brevo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.settings import BREVO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the brevo module.
BREVO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.brevo.brevo.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.url = f"{BREVO_BASE_URL}/contacts"
    resp.reason = "OK" if status_code == 200 else "Client Error"
    resp.headers["Content-Type"] = "application/json"
    return resp


def _make_manager(resume_state: BrevoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

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


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return brevo_source(
        api_key="test-key",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestFormatDatetime:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_datetime(self, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_no_plus_offset(self) -> None:
        assert "+00:00" not in _format_datetime(datetime(2026, 3, 4, tzinfo=UTC))


class TestBuildBaseParams:
    def test_paginated_endpoint_sorts_ascending(self) -> None:
        params = _build_base_params(BREVO_ENDPOINTS["contacts"], False, None, None)
        assert params == {"sort": "asc"}

    def test_non_paginated_endpoint_has_no_sort(self) -> None:
        params = _build_base_params(BREVO_ENDPOINTS["senders"], False, None, None)
        assert params == {}

    @pytest.mark.parametrize(
        ("incremental_field", "expected_param"),
        [("createdAt", "createdSince"), ("modifiedAt", "modifiedSince")],
    )
    def test_incremental_field_maps_to_server_param(self, incremental_field: str, expected_param: str) -> None:
        params = _build_base_params(
            BREVO_ENDPOINTS["contacts"],
            True,
            datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field,
        )
        assert params[expected_param] == "2026-03-04T02:58:14.000Z"

    def test_no_filter_on_first_sync(self) -> None:
        params = _build_base_params(BREVO_ENDPOINTS["contacts"], True, None, "modifiedAt")
        assert "modifiedSince" not in params
        assert "createdSince" not in params

    def test_unknown_incremental_field_is_ignored(self) -> None:
        params = _build_base_params(BREVO_ENDPOINTS["contacts"], True, datetime(2026, 3, 4, tzinfo=UTC), "nonexistent")
        assert params == {"sort": "asc"}


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_offset_advances_and_terminates_on_short_page(self, MockSession, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(BREVO_ENDPOINTS["contacts"], "page_size", 2)
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"contacts": [{"id": 1}, {"id": 2}], "count": 3}),
                _response({"contacts": [{"id": 3}], "count": 3}),
            ],
        )

        rows = _rows(_source("contacts", _make_manager()))

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert [p["offset"] for p in params] == [0, 2]
        assert params[0]["limit"] == 2
        assert params[0]["sort"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_non_terminal_page(self, MockSession, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(BREVO_ENDPOINTS["contacts"], "page_size", 2)
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"contacts": [{"id": 1}, {"id": 2}]}),
                _response({"contacts": [{"id": 3}]}),
            ],
        )

        manager = _make_manager()
        _rows(_source("contacts", manager))

        saved = [saved_call.args[0] for saved_call in manager.save_state.call_args_list]
        assert saved == [BrevoResumeConfig(offset=2)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_terminal_page_does_not_save_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"contacts": [{"id": 1}]})])

        manager = _make_manager()
        _rows(_source("contacts", manager))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_starting_offset(self, MockSession, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(BREVO_ENDPOINTS["contacts"], "page_size", 2)
        session = MockSession.return_value
        params = _wire(session, [_response({"contacts": [{"id": 5}]})])

        manager = _make_manager(BrevoResumeConfig(offset=4))
        _rows(_source("contacts", manager))

        assert params[0]["offset"] == 4
        manager.load_state.assert_called_once()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_load_state_when_cannot_resume(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"contacts": [{"id": 1}]})])

        manager = _make_manager()
        _rows(_source("contacts", manager))

        manager.load_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"contacts": [], "count": 0})])

        rows = _rows(_source("contacts", _make_manager()))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_param_is_sent(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"contacts": [{"id": 1}]})])

        _rows(
            _source(
                "contacts",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="modifiedAt",
            )
        )

        assert params[0]["modifiedSince"] == "2026-03-04T02:58:14.000Z"


class TestNonPaginated:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_senders_fetched_once_without_pagination_params(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"senders": [{"id": 1}, {"id": 2}]})])

        manager = _make_manager()
        rows = _rows(_source("senders", manager))

        assert session.send.call_count == 1
        assert params[0] == {}
        assert rows == [{"id": 1}, {"id": 2}]
        manager.save_state.assert_not_called()


class TestErrors:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_retryable_status_raises(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"message": "Key not found", "code": "unauthorized"}, status_code=401)])

        with pytest.raises(HTTPError):
            _rows(_source("contacts", _make_manager()))

    @pytest.mark.parametrize(
        ("endpoint", "body"),
        [
            # Brevo omits the array key entirely for an empty collection (just {"count": 0}).
            ("email_campaigns", {"count": 0}),
            ("sms_campaigns", {"count": 0}),
            ("contact_segments", {"count": 0}),
            # Some responses set the key to null instead of omitting it.
            ("email_campaigns", {"campaigns": None, "count": 0}),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_or_null_envelope_key_yields_nothing(
        self, MockSession, endpoint: str, body: dict[str, Any]
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response(body)])

        manager = _make_manager()
        rows = _rows(_source(endpoint, manager))

        assert rows == []
        manager.save_state.assert_not_called()


class TestSession:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_session_redacts_key_and_sets_accept_header(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"contacts": [{"id": 1}]})])

        _rows(_source("contacts", _make_manager()))

        # The api key travels via framework auth, so it's registered for value-based redaction
        # rather than being a plain client header.
        assert MockSession.call_args.kwargs["redact_values"] == ("test-key",)
        assert session.headers.get("accept") == "application/json"
        MockSession.assert_called_once()


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with mock.patch(BREVO_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _response({}, status_code=status_code)
            assert validate_credentials("test-key") is expected

    def test_validate_credentials_sends_api_key_header(self) -> None:
        with mock.patch(BREVO_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _response({})
            validate_credentials("test-key")
        assert MockSession.call_args.kwargs["redact_values"] == ("test-key",)
        assert MockSession.return_value.get.call_args.kwargs["headers"]["api-key"] == "test-key"

    def test_validate_credentials_network_error_returns_false(self) -> None:
        with mock.patch(BREVO_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.side_effect = Exception("network down")
            assert validate_credentials("test-key") is False


class TestBrevoSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expects_partition"),
        [
            ("contacts", True),
            ("email_campaigns", True),
            ("sms_campaigns", True),
            ("contact_lists", False),
            ("contact_folders", False),
            ("contact_segments", False),
            ("email_templates", False),
            ("senders", False),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, MockSession, endpoint: str, expects_partition: bool) -> None:
        MockSession.return_value.headers = {}
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

        if expects_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["createdAt"]
            assert response.partition_format == "week"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
