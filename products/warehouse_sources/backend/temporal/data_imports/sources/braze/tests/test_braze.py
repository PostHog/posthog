import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze import (
    BrazeHostNotAllowedError,
    BrazeResumeConfig,
    _format_modified_after,
    _normalize_items,
    braze_source,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braze.settings import BRAZE_ENDPOINTS, ENDPOINTS

BASE_URL = "https://rest.iad-01.braze.com"

# Both the data path and the credential probe build their session via
# make_tracked_session imported into the braze module.
SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session"
HOST_SAFE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze._is_host_safe"


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: BrazeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock | None = None, **kwargs: Any):
    return braze_source(
        "key",
        BASE_URL,
        endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager or _make_manager(),
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://rest.iad-01.braze.com", "https://rest.iad-01.braze.com"),
            ("https://rest.iad-01.braze.com/", "https://rest.iad-01.braze.com"),
            ("https://rest.iad-01.braze.com///", "https://rest.iad-01.braze.com"),
            # Plaintext is upgraded to https; a scheme-less host gets one.
            ("http://rest.iad-01.braze.com", "https://rest.iad-01.braze.com"),
            ("rest.iad-01.braze.com", "https://rest.iad-01.braze.com"),
            ("  https://rest.iad-01.braze.com  ", "https://rest.iad-01.braze.com"),
        ],
    )
    def test_normalizes_to_https(self, value, expected):
        assert normalize_base_url(value) == expected


class TestFormatModifiedAfter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_modified_after(value) == expected


class TestNormalizeItems:
    def test_wraps_scalar_event_names(self):
        items = _normalize_items(BRAZE_ENDPOINTS["events"], ["purchase", "login"])
        assert items == [{"event_name": "purchase"}, {"event_name": "login"}]

    def test_drops_non_dict_rows_for_object_endpoints(self):
        items = _normalize_items(BRAZE_ENDPOINTS["campaigns"], [{"id": "a"}, "garbage", {"id": "b"}])
        assert items == [{"id": "a"}, {"id": "b"}]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Braze API key"),
            (403, False, "Your Braze API key does not have permission for this endpoint"),
            (500, False, "Braze API returned status 500"),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected_valid, expected_message):
        mock_session.return_value.get.return_value = _response({"message": "x"}, status_code=status_code)

        valid, message = validate_credentials("key", BASE_URL)

        assert valid is expected_valid
        assert message == expected_message

    @mock.patch(SESSION_PATCH)
    def test_uses_no_redirect_session_and_probes_with_bearer(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=200)

        validate_credentials("key", BASE_URL)

        assert mock_session.call_args.kwargs["allow_redirects"] is False
        get_call = mock_session.return_value.get.call_args
        assert get_call.args[0] == f"{BASE_URL}/campaigns/list?page=0"
        assert get_call.kwargs["headers"]["Authorization"] == "Bearer key"

    @mock.patch(SESSION_PATCH)
    def test_swallows_request_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = ConnectionError("boom")

        valid, message = validate_credentials("key", BASE_URL)

        assert valid is False
        assert message == "Could not reach the Braze API"

    @mock.patch(HOST_SAFE_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_blocks_internal_host_when_team_id_given(self, mock_session, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        valid, message = validate_credentials("key", "https://10.0.0.1", team_id=42)

        assert valid is False
        assert message == "host not allowed"
        # The host is rejected before any request is dispatched.
        mock_session.return_value.get.assert_not_called()

    @mock.patch(HOST_SAFE_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_skips_host_check_when_team_id_omitted(self, mock_session, mock_host_safe):
        mock_session.return_value.get.return_value = _response({}, status_code=200)

        validate_credentials("key", BASE_URL)

        mock_host_safe.assert_not_called()


class TestGetRows:
    @mock.patch(SESSION_PATCH)
    def test_page_pagination_walks_until_empty(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"campaigns": [{"id": "1"}, {"id": "2"}]}),
                _response({"campaigns": [{"id": "3"}]}),
                _response({"campaigns": []}),
            ],
        )

        rows = _rows(_source("campaigns"))

        assert [row["id"] for row in rows] == ["1", "2", "3"]
        assert [p["page"] for p in params] == [0, 1, 2]

    @mock.patch(SESSION_PATCH)
    def test_offset_pagination_advances_by_page_size(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"templates": [{"email_template_id": "a"}]}),
                _response({"templates": []}),
            ],
        )

        _rows(_source("email_templates"))

        # First page omits offset (Braze rejects offset=0); later pages advance by page size.
        assert "offset" not in params[0]
        assert params[0]["limit"] == 100
        assert params[1]["offset"] == 100

    @mock.patch(SESSION_PATCH)
    def test_offset_pagination_continues_past_short_page(self, MockSession):
        # A short (non-empty) page is not the last one — only an empty page terminates.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"templates": [{"email_template_id": "a"}]}),
                _response({"templates": [{"email_template_id": "b"}]}),
                _response({"templates": []}),
            ],
        )

        rows = _rows(_source("email_templates"))

        assert [row["email_template_id"] for row in rows] == ["a", "b"]
        assert [p.get("offset") for p in params] == [None, 100, 200]

    @mock.patch(SESSION_PATCH)
    def test_uses_no_redirect_session_with_redacted_key(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"campaigns": []})])

        _rows(_source("campaigns"))

        assert MockSession.call_args.kwargs["allow_redirects"] is False
        assert "key" in MockSession.call_args.kwargs["redact_values"]

    @mock.patch(SESSION_PATCH)
    def test_saves_next_cursor_after_each_yield(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"campaigns": [{"id": "1"}]}),
                _response({"campaigns": [{"id": "2"}]}),
                _response({"campaigns": []}),
            ],
        )

        manager = _make_manager()
        _rows(_source("campaigns", manager))

        saved = [call.args[0].cursor for call in manager.save_state.call_args_list]
        # Checkpoints point at the next unfetched page; the terminal empty page saves nothing.
        assert saved == [1, 2]

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response({"campaigns": [{"id": "9"}]}), _response({"campaigns": []})])

        _rows(_source("campaigns", _make_manager(BrazeResumeConfig(cursor=5))))

        assert params[0]["page"] == 5

    @mock.patch(SESSION_PATCH)
    def test_resumes_offset_endpoint_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response({"templates": []})])

        _rows(_source("email_templates", _make_manager(BrazeResumeConfig(cursor=200))))

        assert params[0]["offset"] == 200
        assert params[0]["limit"] == 100

    @mock.patch(SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"campaigns": []})])

        manager = _make_manager()
        batches = list(_source("campaigns", manager).items())

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(SESSION_PATCH)
    def test_missing_data_key_ends_pagination_without_error(self, MockSession):
        # Braze omits the data key when there is nothing to return — a normal end of data.
        session = MockSession.return_value
        _wire(session, [_response({"message": "success"})])

        batches = list(_source("campaigns").items())

        assert batches == []
        assert session.send.call_count == 1

    @mock.patch(SESSION_PATCH)
    def test_incremental_applies_modified_after_filter(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"templates": [{"email_template_id": "a", "updated_at": "2026-02-01T00:00:00Z"}]}),
                _response({"templates": []}),
            ],
        )

        _rows(
            _source(
                "email_templates",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert params[0]["modified_after"] == "2026-01-01T00:00:00+00:00"
        # The filter is carried on every page of the run.
        assert params[1]["modified_after"] == "2026-01-01T00:00:00+00:00"

    @mock.patch(SESSION_PATCH)
    def test_full_refresh_endpoint_never_sends_modified_after(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"campaigns": [{"id": "1"}]}),
                _response({"campaigns": []}),
            ],
        )

        _rows(
            _source(
                "campaigns",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert all("modified_after" not in p for p in params)

    @mock.patch(SESSION_PATCH)
    def test_events_endpoint_wraps_scalar_rows(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"events": ["purchase", "login"]}), _response({"events": []})])

        rows = _rows(_source("events"))

        assert rows == [{"event_name": "purchase"}, {"event_name": "login"}]

    @mock.patch(SESSION_PATCH)
    def test_drops_non_dict_rows_from_object_endpoint(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"campaigns": [{"id": "a"}, "garbage"]}), _response({"campaigns": []})])

        rows = _rows(_source("campaigns"))

        assert rows == [{"id": "a"}]

    @mock.patch(HOST_SAFE_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_raises_when_host_not_allowed(self, MockSession, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        response = braze_source(
            "key",
            "https://10.0.0.1",
            "campaigns",
            team_id=42,
            job_id="job",
            resumable_source_manager=_make_manager(),
        )
        with pytest.raises(BrazeHostNotAllowedError):
            list(response.items())

        # No request is made once the host is rejected.
        MockSession.return_value.send.assert_not_called()


class TestBrazeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = BRAZE_ENDPOINTS[endpoint]
        response = _source(endpoint)

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(BRAZE_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        # Partition keys must be immutable creation timestamps, never updated/last-edit fields.
        if config.partition_key:
            assert config.partition_key == "created_at"
