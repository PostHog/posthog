import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.omni import omni as omni_module
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.omni import (
    OmniDocumentsPaginator,
    OmniPageInfoPaginator,
    OmniResumeConfig,
    OmniScimPaginator,
    _base_api_url,
    _format_watermark,
    _hostname,
    get_endpoint_permissions,
    get_key_scope,
    get_resource,
    normalize_host,
    omni_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.settings import PARTITION_KEYS, PRIMARY_KEYS

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
OMNI_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.omni.omni.make_tracked_session"


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _make_manager(resume_state: OmniResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://acme.omniapp.co", "https://acme.omniapp.co"),
            ("acme.omniapp.co", "https://acme.omniapp.co"),
            ("https://acme.omniapp.co/api", "https://acme.omniapp.co"),
            ("http://acme.omniapp.co", "https://acme.omniapp.co"),
            ("http://localhost:8080", "http://localhost:8080"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected

    def test_hostname_extracts_bare_host(self):
        assert _hostname("https://acme.omniapp.co/api") == "acme.omniapp.co"

    def test_base_api_url_appends_api_path(self):
        assert _base_api_url("acme.omniapp.co") == "https://acme.omniapp.co/api"


class TestFormatWatermark:
    def test_formats_datetime_with_millisecond_precision(self):
        import datetime

        value = datetime.datetime(2026, 6, 1, 14, 30, 0, 500000, tzinfo=datetime.UTC)
        assert _format_watermark(value) == "2026-06-01T14:30:00.500Z"

    def test_naive_datetime_assumed_utc(self):
        import datetime

        value = datetime.datetime(2026, 6, 1, 14, 30, 0)
        assert _format_watermark(value) == "2026-06-01T14:30:00.000Z"

    def test_string_value_passed_through(self):
        assert _format_watermark("2026-06-01T14:30:00.000Z") == "2026-06-01T14:30:00.000Z"

    @pytest.mark.parametrize("value", [None, "", 123])
    def test_unsupported_values_return_none(self, value):
        assert _format_watermark(value) is None


class TestOmniPageInfoPaginator:
    def test_initial_request_has_no_cursor(self):
        paginator = OmniPageInfoPaginator(page_size=50)
        request = Request(method="GET", url="https://acme.omniapp.co/api/v1/documents")
        paginator.init_request(request)

        assert request.params["pageSize"] == 50
        assert "cursor" not in request.params

    def test_update_state_has_next_page(self):
        paginator = OmniPageInfoPaginator()
        response = _make_response({"pageInfo": {"hasNextPage": True, "nextCursor": "abc"}, "records": []})
        paginator.update_state(response)

        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"cursor": "abc"}

    def test_update_state_terminal_page(self):
        paginator = OmniPageInfoPaginator()
        response = _make_response({"pageInfo": {"hasNextPage": False, "nextCursor": None}, "records": []})
        paginator.update_state(response)

        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None

    def test_has_next_page_true_but_no_cursor_treated_as_terminal(self):
        # Defensive: hasNextPage=True with a missing nextCursor shouldn't spin forever.
        paginator = OmniPageInfoPaginator()
        response = _make_response({"pageInfo": {"hasNextPage": True, "nextCursor": None}, "records": []})
        paginator.update_state(response)

        assert paginator.has_next_page is False

    def test_malformed_body_treated_as_terminal(self):
        paginator = OmniPageInfoPaginator()
        response = _make_response({})
        paginator.update_state(response)

        assert paginator.has_next_page is False

    def test_set_resume_state_seeds_cursor(self):
        paginator = OmniPageInfoPaginator()
        paginator.set_resume_state({"cursor": "resumed-cursor"})

        request = Request(method="GET", url="https://acme.omniapp.co/api/v1/documents")
        paginator.init_request(request)
        assert request.params["cursor"] == "resumed-cursor"

    def test_set_resume_state_ignores_missing_cursor(self):
        paginator = OmniPageInfoPaginator()
        paginator.set_resume_state({})
        assert paginator.get_resume_state() is None


class TestOmniDocumentsPaginator:
    def test_full_sync_never_stops_early(self):
        paginator = OmniDocumentsPaginator(stop_when_older_than=None)
        response = _make_response({"pageInfo": {"hasNextPage": True, "nextCursor": "c1"}, "records": []})
        data = [{"updatedAt": "2020-01-01T00:00:00.000Z"}]
        paginator.update_state(response, data)

        assert paginator.has_next_page is True

    def test_incremental_stops_once_page_predates_watermark(self):
        paginator = OmniDocumentsPaginator(stop_when_older_than="2026-01-01T00:00:00.000Z")
        response = _make_response({"pageInfo": {"hasNextPage": True, "nextCursor": "c1"}, "records": []})
        data = [
            {"updatedAt": "2025-06-01T00:00:00.000Z"},
            {"updatedAt": "2025-05-01T00:00:00.000Z"},
        ]
        paginator.update_state(response, data)

        assert paginator.has_next_page is False

    def test_incremental_keeps_paginating_when_page_has_newer_rows(self):
        paginator = OmniDocumentsPaginator(stop_when_older_than="2026-01-01T00:00:00.000Z")
        response = _make_response({"pageInfo": {"hasNextPage": True, "nextCursor": "c1"}, "records": []})
        data = [
            {"updatedAt": "2026-06-01T00:00:00.000Z"},
            {"updatedAt": "2025-05-01T00:00:00.000Z"},
        ]
        paginator.update_state(response, data)

        assert paginator.has_next_page is True

    def test_null_updated_at_does_not_force_early_stop(self):
        # A page with only null `updatedAt` values can't be judged against the watermark, so
        # pagination continues rather than risk skipping unsynced rows.
        paginator = OmniDocumentsPaginator(stop_when_older_than="2026-01-01T00:00:00.000Z")
        response = _make_response({"pageInfo": {"hasNextPage": True, "nextCursor": "c1"}, "records": []})
        data = [{"updatedAt": None}, {"identifier": "no-updated-at-key"}]
        paginator.update_state(response, data)

        assert paginator.has_next_page is True


class TestOmniScimPaginator:
    def test_initial_request_starts_at_index_one(self):
        paginator = OmniScimPaginator(count=50)
        request = Request(method="GET", url="https://acme.omniapp.co/api/scim/v2/users")
        paginator.init_request(request)

        assert request.params == {"count": 50, "startIndex": 1}

    def test_advances_start_index_when_more_results_remain(self):
        paginator = OmniScimPaginator(count=100)
        response = _make_response({"Resources": [], "itemsPerPage": 100, "totalResults": 250, "startIndex": 1})
        paginator.update_state(response)

        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"start_index": 101}

    def test_stops_when_all_results_returned(self):
        paginator = OmniScimPaginator(count=100)
        response = _make_response({"Resources": [], "itemsPerPage": 50, "totalResults": 50, "startIndex": 1})
        paginator.update_state(response)

        assert paginator.has_next_page is False

    def test_stops_on_empty_page(self):
        paginator = OmniScimPaginator(count=100)
        response = _make_response({"Resources": [], "itemsPerPage": 0, "totalResults": 0, "startIndex": 1})
        paginator.update_state(response)

        assert paginator.has_next_page is False

    def test_set_resume_state_seeds_start_index(self):
        paginator = OmniScimPaginator()
        paginator.set_resume_state({"start_index": 201})

        request = Request(method="GET", url="https://acme.omniapp.co/api/scim/v2/users")
        paginator.init_request(request)
        assert request.params["startIndex"] == 201


class TestGetResource:
    @pytest.mark.parametrize(
        "endpoint, expected_path, expected_selector",
        [
            ("Documents", "/v1/documents", "records"),
            ("Folders", "/v1/folders", "records"),
            ("Connections", "/v1/connections", "connections"),
            ("Schedules", "/v1/schedules", "records"),
            ("Users", "/scim/v2/users", "Resources"),
            ("UserGroups", "/scim/v2/groups", "Resources"),
        ],
    )
    def test_endpoint_shape(self, endpoint, expected_path, expected_selector):
        resource = get_resource(endpoint, should_use_incremental_field=False, stop_when_older_than=None)
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)

        assert endpoint_config["path"] == expected_path
        assert endpoint_config["data_selector"] == expected_selector

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError):
            get_resource("Nope", should_use_incremental_field=False, stop_when_older_than=None)

    def test_documents_incremental_uses_merge(self):
        resource = get_resource("Documents", should_use_incremental_field=True, stop_when_older_than="x")
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    def test_documents_full_refresh_uses_replace(self):
        resource = get_resource("Documents", should_use_incremental_field=False, stop_when_older_than=None)
        assert resource["write_disposition"] == "replace"

    @pytest.mark.parametrize("endpoint", ["Folders", "Connections", "Schedules", "Users", "UserGroups"])
    def test_non_incremental_endpoints_always_replace(self, endpoint):
        resource = get_resource(endpoint, should_use_incremental_field=True, stop_when_older_than=None)
        assert resource["write_disposition"] == "replace"

    def test_documents_sorts_newest_first(self):
        resource = get_resource("Documents", should_use_incremental_field=False, stop_when_older_than=None)
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        assert endpoint_config["params"] == {"sortField": "updatedAt", "sortDirection": "desc"}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, schema_name, expected_valid",
        [
            (200, None, True),
            (200, "Documents", True),
            (401, None, False),
            (401, "Documents", False),
            (403, None, True),
            (403, "Documents", False),
            (500, None, False),
        ],
    )
    @mock.patch.object(omni_module, "_is_host_safe", return_value=(True, None))
    @mock.patch(OMNI_SESSION_PATCH)
    def test_validate_credentials_status_mapping(
        self, mock_session, _mock_host_safe, status_code, schema_name, expected_valid
    ):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        is_valid, error = validate_credentials("acme.omniapp.co", "test-key", team_id=1, schema_name=schema_name)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error

    @mock.patch.object(omni_module, "_is_host_safe", return_value=(False, "internal address"))
    def test_validate_credentials_blocks_unsafe_host(self, _mock_host_safe):
        is_valid, error = validate_credentials("169.254.169.254", "test-key", team_id=1)

        assert is_valid is False
        assert error == "internal address"

    def test_validate_credentials_rejects_invalid_hostname(self):
        is_valid, error = validate_credentials("not a host!!", "test-key", team_id=1)
        assert is_valid is False
        assert error

    @mock.patch.object(omni_module, "_is_host_safe", return_value=(True, None))
    @mock.patch(OMNI_SESSION_PATCH)
    def test_sends_bearer_token(self, mock_session, _mock_host_safe):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("acme.omniapp.co", "test-key", team_id=1)

        _, kwargs = mock_session.return_value.get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"


class TestGetKeyScope:
    @mock.patch(OMNI_SESSION_PATCH)
    def test_returns_key_scope_on_success(self, mock_session):
        response = mock.MagicMock(status_code=200)
        response.json.return_value = {"keyScope": "organization"}
        mock_session.return_value.get.return_value = response

        assert get_key_scope("acme.omniapp.co", "test-key") == "organization"

    @mock.patch(OMNI_SESSION_PATCH)
    def test_returns_none_on_error_status(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert get_key_scope("acme.omniapp.co", "test-key") is None

    @mock.patch(OMNI_SESSION_PATCH)
    def test_returns_none_on_request_exception(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert get_key_scope("acme.omniapp.co", "test-key") is None


class TestGetEndpointPermissions:
    def test_no_scim_endpoints_requested_returns_all_reachable(self):
        result = get_endpoint_permissions("acme.omniapp.co", "test-key", ["Documents", "Folders"])
        assert result == {"Documents": None, "Folders": None}

    @mock.patch.object(omni_module, "get_key_scope", return_value="user")
    def test_pat_scope_blocks_scim_endpoints(self, _mock_scope):
        result = get_endpoint_permissions("acme.omniapp.co", "test-key", ["Documents", "Users", "UserGroups"])

        assert result["Documents"] is None
        assert result["Users"] is not None
        assert result["UserGroups"] is not None

    @mock.patch.object(omni_module, "get_key_scope", return_value="organization")
    def test_org_scope_allows_scim_endpoints(self, _mock_scope):
        result = get_endpoint_permissions("acme.omniapp.co", "test-key", ["Users", "UserGroups"])
        assert result == {"Users": None, "UserGroups": None}

    @mock.patch.object(omni_module, "get_key_scope", return_value=None)
    def test_unknown_scope_allows_scim_endpoints(self, _mock_scope):
        # Can't confirm the scope (probe failed) — don't block on a guess; sync-time errors are
        # handled separately by get_non_retryable_errors.
        result = get_endpoint_permissions("acme.omniapp.co", "test-key", ["Users"])
        assert result == {"Users": None}


class TestOmniSourceEndToEnd:
    def _drive(self, endpoint: str, manager: mock.MagicMock, responses: list[Response], **kwargs: Any):
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            response = omni_source(
                host="acme.omniapp.co",
                api_key="test-key",
                endpoint=endpoint,
                team_id=1,
                job_id="job-1",
                resumable_source_manager=manager,
                **kwargs,
            )
            rows = [row for page in cast(Iterable[Any], response.items()) for row in page]
            return response, rows, sent_params

    def test_documents_pagination_and_checkpointing(self):
        manager = _make_manager()
        responses = [
            _make_response(
                {
                    "pageInfo": {"hasNextPage": True, "nextCursor": "cursor-1"},
                    "records": [{"identifier": "d1", "updatedAt": "2026-01-02T00:00:00.000Z"}],
                }
            ),
            _make_response(
                {
                    "pageInfo": {"hasNextPage": False, "nextCursor": None},
                    "records": [{"identifier": "d2", "updatedAt": "2026-01-01T00:00:00.000Z"}],
                }
            ),
        ]
        _, rows, sent_params = self._drive("Documents", manager, responses)

        assert len(rows) == 2
        assert sent_params[0].get("sortField") == "updatedAt"
        assert sent_params[0].get("sortDirection") == "desc"
        assert "cursor" not in sent_params[0]
        assert sent_params[1]["cursor"] == "cursor-1"
        manager.save_state.assert_called_once_with(OmniResumeConfig(cursor="cursor-1"))

    def test_documents_resumes_from_saved_cursor(self):
        manager = _make_manager(OmniResumeConfig(cursor="resumed-cursor"))
        responses = [_make_response({"pageInfo": {"hasNextPage": False, "nextCursor": None}, "records": []})]

        _, _rows, sent_params = self._drive("Documents", manager, responses)

        assert sent_params[0]["cursor"] == "resumed-cursor"
        manager.load_state.assert_called_once()

    def test_connections_single_page_never_checkpoints(self):
        manager = _make_manager()
        responses = [_make_response({"connections": [{"id": "c1"}, {"id": "c2"}]})]

        _, rows, _sent_params = self._drive("Connections", manager, responses)

        assert rows == [{"id": "c1"}, {"id": "c2"}]
        manager.save_state.assert_not_called()

    def test_users_scim_pagination_checkpoints_start_index(self):
        manager = _make_manager()
        responses = [
            _make_response(
                {"Resources": [{"id": "u1"}], "itemsPerPage": 1, "totalResults": 2, "startIndex": 1},
            ),
            _make_response(
                {"Resources": [{"id": "u2"}], "itemsPerPage": 1, "totalResults": 2, "startIndex": 2},
            ),
        ]
        _, rows, _sent_params = self._drive("Users", manager, responses)

        assert rows == [{"id": "u1"}, {"id": "u2"}]
        manager.save_state.assert_called_once_with(OmniResumeConfig(start_index=2))

    @pytest.mark.parametrize("endpoint", list(PRIMARY_KEYS.keys()))
    def test_response_metadata_per_endpoint(self, endpoint):
        manager = _make_manager()
        selector = {
            "Documents": "records",
            "Folders": "records",
            "Connections": "connections",
            "Schedules": "records",
            "Users": "Resources",
            "UserGroups": "Resources",
        }[endpoint]
        responses = [
            _make_response({"pageInfo": {"hasNextPage": False, "nextCursor": None}, selector: []})
            if selector != "connections"
            else _make_response({selector: []})
        ]

        response, _rows, _sent_params = self._drive(endpoint, manager, responses)

        assert response.primary_keys == PRIMARY_KEYS[endpoint]
        assert response.sort_mode == ("desc" if endpoint == "Documents" else "asc")
        partition_key = PARTITION_KEYS[endpoint]
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestOmniSourceSsrfGuards:
    @mock.patch.object(omni_module, "_is_host_safe", return_value=(False, "internal address"))
    def test_sync_rejects_unsafe_host(self, _mock_host_safe):
        # A hostname that validated publicly can be DNS-rebound to a private address before a
        # scheduled import runs; the sync must re-check rather than trust the stored host.
        with pytest.raises(ValueError, match="internal address"):
            omni_source(
                host="acme.omniapp.co",
                api_key="test-key",
                endpoint="Connections",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(),
            )

    @mock.patch.object(omni_module, "_is_host_safe", return_value=(True, None))
    def test_sync_pins_host_and_disables_redirects(self, _mock_host_safe):
        send_kwargs: list[dict[str, Any]] = []

        def fake_send(request: Any, *_args: Any, **kwargs: Any) -> Response:
            send_kwargs.append(kwargs)
            return _make_response({"connections": []})

        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            response = omni_source(
                host="acme.omniapp.co",
                api_key="test-key",
                endpoint="Connections",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(),
            )
            list(cast(Iterable[Any], response.items()))

        # Redirects are never followed, so a 3xx can't bounce the bearer token off-host.
        assert send_kwargs and all(kw.get("allow_redirects") is False for kw in send_kwargs)
