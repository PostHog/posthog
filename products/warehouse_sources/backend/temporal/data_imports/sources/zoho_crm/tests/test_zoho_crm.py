from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.settings import ZOHO_CRM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.zoho_crm import (
    MAX_FIELDS_PER_REQUEST,
    MAX_PAGE,
    PAGE_SIZE,
    REFRESH_TOKEN_REJECTED_MESSAGE,
    ZohoCRMAuthError,
    ZohoCRMClient,
    ZohoCRMResumeConfig,
    chunk_fields,
    format_modified_since,
    get_rows,
    readable_field_names,
    resolve_hosts,
    validate_credentials,
    zoho_crm_source,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.zoho_crm"


class FakeResumeManager(ResumableSourceManager[ZohoCRMResumeConfig]):
    """In-memory stand-in for the Redis-backed manager."""

    def __init__(self, state: Optional[ZohoCRMResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[ZohoCRMResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[ZohoCRMResumeConfig]:
        return self.state

    def save_state(self, data: ZohoCRMResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def _response(status_code: int = 200, body: Optional[dict[str, Any]] = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.json.return_value = body if body is not None else {}
    return response


def _token_response(api_domain: str = "https://www.zohoapis.com") -> mock.MagicMock:
    return _response(200, {"access_token": "access-token", "api_domain": api_domain, "expires_in": 3600})


def _fields_response(count: int) -> mock.MagicMock:
    return _response(200, {"fields": [{"api_name": f"Field_{index}"} for index in range(count)]})


def _records_response(
    records: list[dict[str, Any]],
    more_records: bool = False,
    next_page_token: Optional[str] = None,
    data_key: str = "data",
) -> mock.MagicMock:
    info: dict[str, Any] = {"more_records": more_records, "per_page": PAGE_SIZE}
    if next_page_token is not None:
        info["next_page_token"] = next_page_token
    return _response(200, {data_key: records, "info": info})


def _session(
    get_responses: list[mock.MagicMock], post_responses: Optional[list[mock.MagicMock]] = None
) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get.side_effect = list(get_responses)
    session.post.side_effect = list(post_responses) if post_responses is not None else [_token_response()]
    return session


def _client() -> ZohoCRMClient:
    return ZohoCRMClient("us", "cid", "secret", "refresh")


def _get_params(session: mock.MagicMock, index: int) -> dict[str, str]:
    return cast(dict[str, str], session.get.call_args_list[index].kwargs["params"])


def _get_headers(session: mock.MagicMock, index: int) -> dict[str, str]:
    return cast(dict[str, str], session.get.call_args_list[index].kwargs["headers"])


class TestResolveHosts:
    @pytest.mark.parametrize(
        "region, accounts_host, api_host",
        [
            ("us", "https://accounts.zoho.com", "https://www.zohoapis.com"),
            ("eu", "https://accounts.zoho.eu", "https://www.zohoapis.eu"),
            ("in", "https://accounts.zoho.in", "https://www.zohoapis.in"),
            ("au", "https://accounts.zoho.com.au", "https://www.zohoapis.com.au"),
            ("jp", "https://accounts.zoho.jp", "https://www.zohoapis.jp"),
            ("ca", "https://accounts.zohocloud.ca", "https://www.zohoapis.ca"),
            ("cn", "https://accounts.zoho.com.cn", "https://www.zohoapis.com.cn"),
        ],
    )
    def test_regional_hosts(self, region: str, accounts_host: str, api_host: str) -> None:
        assert resolve_hosts(region) == (accounts_host, api_host)

    def test_unknown_region_raises(self) -> None:
        with pytest.raises(ValueError):
            resolve_hosts("mars")


class TestFormatModifiedSince:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 3, 1, 12, 30, 15, tzinfo=UTC), "2024-03-01T12:30:15+00:00"),
            (datetime(2024, 3, 1, 12, 30, 15), "2024-03-01T12:30:15+00:00"),
            (date(2024, 3, 1), "2024-03-01T00:00:00+00:00"),
            ("2024-03-01T00:00:00+00:00", "2024-03-01T00:00:00+00:00"),
        ],
    )
    def test_formats_cursor_values(self, value: Any, expected: str) -> None:
        assert format_modified_since(value) == expected


class TestChunkFields:
    @pytest.mark.parametrize(
        "count, expected_sizes",
        [
            (0, [0]),
            (1, [1]),
            (MAX_FIELDS_PER_REQUEST, [MAX_FIELDS_PER_REQUEST]),
            (MAX_FIELDS_PER_REQUEST + 1, [MAX_FIELDS_PER_REQUEST, 1]),
            (MAX_FIELDS_PER_REQUEST * 2 + 3, [MAX_FIELDS_PER_REQUEST, MAX_FIELDS_PER_REQUEST, 3]),
        ],
    )
    def test_slices_never_exceed_the_request_cap(self, count: int, expected_sizes: list[int]) -> None:
        slices = chunk_fields([f"Field_{index}" for index in range(count)])
        assert [len(chunk) for chunk in slices] == expected_sizes


class TestZohoCRMClient:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_token_response_api_domain_overrides_regional_default(self, make_session: mock.MagicMock) -> None:
        make_session.return_value = _session([], post_responses=[_token_response("https://www.zohoapis.eu/")])
        client = ZohoCRMClient("us", "cid", "secret", "refresh")

        client.mint_access_token()

        assert client.api_domain == "https://www.zohoapis.eu"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_error_body_on_a_200_raises_auth_error(self, make_session: mock.MagicMock) -> None:
        make_session.return_value = _session([], post_responses=[_response(200, {"error": "invalid_code"})])
        client = _client()

        with pytest.raises(ZohoCRMAuthError, match="invalid_code"):
            client.mint_access_token()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_authorization_header_uses_the_zoho_scheme(self, make_session: mock.MagicMock) -> None:
        session = _session([_response(200, {"modules": []})])
        make_session.return_value = session

        _client().get("/crm/v8/settings/modules")

        assert _get_headers(session, 0)["Authorization"] == "Zoho-oauthtoken access-token"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_remints_once_on_401_and_replays_the_request(self, make_session: mock.MagicMock) -> None:
        session = _session(
            [_response(401), _response(200, {"data": []})],
            post_responses=[_token_response(), _token_response()],
        )
        make_session.return_value = session

        response = _client().get("/crm/v8/Leads")

        assert response.status_code == 200
        assert session.post.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_204_is_returned_without_raising(self, make_session: mock.MagicMock) -> None:
        no_content = _response(204)
        no_content.raise_for_status.side_effect = AssertionError("204 must not be treated as an error")
        make_session.return_value = _session([no_content])

        assert _client().get("/crm/v8/Leads").status_code == 204

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_session_disables_sample_capture_and_redacts_credentials(self, make_session: mock.MagicMock) -> None:
        # Reverting capture=False would upload raw CRM records (contacts, notes, emails) and the
        # minted access token to the shared HTTP sample-capture prefix.
        make_session.return_value = _session([])

        ZohoCRMClient("us", "cid", "secret-value", "refresh-value")

        assert make_session.call_args.kwargs == {"redact_values": ("secret-value", "refresh-value"), "capture": False}


class TestReadableFieldNames:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_skips_fields_the_api_never_returns(self, make_session: mock.MagicMock) -> None:
        make_session.return_value = _session(
            [
                _response(
                    200,
                    {
                        "fields": [
                            {"api_name": "Last_Name", "view_type": {"view": True}},
                            {"api_name": "Hidden", "view_type": {"view": False}},
                            {"api_name": "No_View_Type"},
                            {"data_type": "text"},
                        ]
                    },
                )
            ]
        )

        assert readable_field_names(_client(), "v8", "Leads") == ["Last_Name", "No_View_Type"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_204_metadata_yields_no_projection(self, make_session: mock.MagicMock) -> None:
        make_session.return_value = _session([_response(204)])

        assert readable_field_names(_client(), "v8", "Leads") == []


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_single_page_module_requests_its_fields_and_clears_state(self, make_session: mock.MagicMock) -> None:
        session = _session([_fields_response(3), _records_response([{"id": "1"}, {"id": "2"}])])
        make_session.return_value = session
        manager = FakeResumeManager()

        batches = list(get_rows(_client(), "v8", "Leads", manager, mock.MagicMock()))

        assert batches == [[{"id": "1"}, {"id": "2"}]]
        records_params = _get_params(session, 1)
        assert records_params["fields"] == "Field_0,Field_1,Field_2"
        assert records_params["per_page"] == str(PAGE_SIZE)
        assert records_params["page"] == "1"
        assert manager.saved == []
        assert manager.cleared is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_sorts_by_the_immutable_id(self, make_session: mock.MagicMock) -> None:
        session = _session([_fields_response(1), _records_response([{"id": "1"}])])
        make_session.return_value = session

        list(get_rows(_client(), "v8", "Leads", FakeResumeManager(), mock.MagicMock()))

        assert _get_params(session, 1)["sort_by"] == "id"
        assert _get_params(session, 1)["sort_order"] == "asc"
        assert "If-Modified-Since" not in _get_headers(session, 1)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_sync_filters_and_sorts_on_the_cursor_field(self, make_session: mock.MagicMock) -> None:
        session = _session([_fields_response(1), _records_response([{"id": "1"}])])
        make_session.return_value = session

        list(
            get_rows(
                _client(),
                "v8",
                "Contacts",
                FakeResumeManager(),
                mock.MagicMock(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 6, 1, tzinfo=UTC),
                incremental_field="Modified_Time",
            )
        )

        assert _get_headers(session, 1)["If-Modified-Since"] == "2024-06-01T00:00:00+00:00"
        assert _get_params(session, 1)["sort_by"] == "Modified_Time"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_by_page_then_by_token_and_checkpoints_each_page(self, make_session: mock.MagicMock) -> None:
        session = _session(
            [
                _fields_response(1),
                _records_response([{"id": "1"}], more_records=True),
                _records_response([{"id": "2"}], more_records=True, next_page_token="tok-2"),
                _records_response([{"id": "3"}], more_records=False),
            ]
        )
        make_session.return_value = session
        manager = FakeResumeManager()

        batches = list(get_rows(_client(), "v8", "Leads", manager, mock.MagicMock()))

        assert batches == [[{"id": "1"}], [{"id": "2"}], [{"id": "3"}]]
        assert _get_params(session, 2)["page"] == "2"
        assert "page_token" not in _get_params(session, 2)
        assert _get_params(session, 3)["page_token"] == "tok-2"
        assert "page" not in _get_params(session, 3)
        assert [(state.page, state.page_tokens) for state in manager.saved] == [(2, []), (3, ["tok-2"])]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_stops_when_the_api_reports_no_more_records(self, make_session: mock.MagicMock) -> None:
        session = _session([_fields_response(1), _records_response([{"id": "1"}], more_records=False)])
        make_session.return_value = session

        list(get_rows(_client(), "v8", "Leads", FakeResumeManager(), mock.MagicMock()))

        assert session.get.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_page_stops_pagination_even_when_more_records_is_set(self, make_session: mock.MagicMock) -> None:
        session = _session([_fields_response(1), _records_response([], more_records=True)])
        make_session.return_value = session

        assert list(get_rows(_client(), "v8", "Leads", FakeResumeManager(), mock.MagicMock())) == []
        assert session.get.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_204_module_response_yields_nothing(self, make_session: mock.MagicMock) -> None:
        session = _session([_fields_response(1), _response(204)])
        make_session.return_value = session

        assert list(get_rows(_client(), "v8", "Leads", FakeResumeManager(), mock.MagicMock())) == []

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_stops_at_the_page_window_when_no_token_is_offered(self, make_session: mock.MagicMock) -> None:
        pages = [_records_response([{"id": str(page)}], more_records=True) for page in range(MAX_PAGE + 2)]
        session = _session([_fields_response(1), *pages])
        make_session.return_value = session
        logger = mock.MagicMock()

        batches = list(get_rows(_client(), "v8", "Leads", FakeResumeManager(), logger))

        assert len(batches) == MAX_PAGE
        logger.warning.assert_called_once()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_wide_module_merges_its_field_slices_per_page(self, make_session: mock.MagicMock) -> None:
        session = _session(
            [
                _fields_response(MAX_FIELDS_PER_REQUEST + 2),
                _records_response([{"id": "1", "Field_0": "a"}, {"id": "2", "Field_0": "b"}]),
                _records_response([{"id": "1", "Field_50": "x"}, {"id": "2", "Field_50": "y"}]),
            ]
        )
        make_session.return_value = session

        batches = list(get_rows(_client(), "v8", "Leads", FakeResumeManager(), mock.MagicMock()))

        assert batches == [
            [
                {"id": "1", "Field_0": "a", "Field_50": "x"},
                {"id": "2", "Field_0": "b", "Field_50": "y"},
            ]
        ]
        assert len(_get_params(session, 1)["fields"].split(",")) == MAX_FIELDS_PER_REQUEST
        assert _get_params(session, 2)["fields"] == "Field_50,Field_51"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_the_saved_page_token(self, make_session: mock.MagicMock) -> None:
        session = _session([_fields_response(1), _records_response([{"id": "9"}])])
        make_session.return_value = session
        manager = FakeResumeManager(ZohoCRMResumeConfig(page=12, page_tokens=["tok-11"]))

        batches = list(get_rows(_client(), "v8", "Leads", manager, mock.MagicMock()))

        assert batches == [[{"id": "9"}]]
        assert _get_params(session, 1)["page_token"] == "tok-11"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_the_saved_page_number_within_the_window(self, make_session: mock.MagicMock) -> None:
        session = _session([_fields_response(1), _records_response([{"id": "9"}])])
        make_session.return_value = session
        manager = FakeResumeManager(ZohoCRMResumeConfig(page=3, page_tokens=[]))

        list(get_rows(_client(), "v8", "Leads", manager, mock.MagicMock()))

        assert _get_params(session, 1)["page"] == "3"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_restarts_when_saved_tokens_no_longer_match_the_field_slices(self, make_session: mock.MagicMock) -> None:
        # Two slices now, but the checkpoint only carries one token — the tokens are unusable.
        session = _session(
            [
                _fields_response(MAX_FIELDS_PER_REQUEST + 1),
                _records_response([{"id": "1"}]),
                _records_response([{"id": "1"}]),
            ]
        )
        make_session.return_value = session
        manager = FakeResumeManager(ZohoCRMResumeConfig(page=25, page_tokens=["stale"]))

        list(get_rows(_client(), "v8", "Leads", manager, mock.MagicMock()))

        assert _get_params(session, 1)["page"] == "1"
        assert "page_token" not in _get_params(session, 1)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_users_endpoint_skips_field_metadata_and_reads_its_own_envelope(self, make_session: mock.MagicMock) -> None:
        session = _session([_records_response([{"id": "u1"}], data_key="users")])
        make_session.return_value = session

        batches = list(get_rows(_client(), "v8", "Users", FakeResumeManager(), mock.MagicMock()))

        assert batches == [[{"id": "u1"}]]
        assert session.get.call_count == 1
        assert session.get.call_args_list[0].args[0] == "https://www.zohoapis.com/crm/v8/users"
        assert _get_params(session, 0)["type"] == "AllUsers"
        assert "sort_by" not in _get_params(session, 0)
        assert "fields" not in _get_params(session, 0)


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_when_the_modules_probe_succeeds(self, make_session: mock.MagicMock) -> None:
        make_session.return_value = _session([_response(200, {"modules": []})])

        assert validate_credentials("us", "cid", "secret", "refresh") == (True, None)

    def test_unknown_region_is_rejected_without_a_request(self) -> None:
        is_valid, error = validate_credentials("mars", "cid", "secret", "refresh")

        assert is_valid is False
        assert error is not None and "mars" in error

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_refresh_token_rejection_gives_actionable_copy(self, make_session: mock.MagicMock) -> None:
        # The raw Zoho OAuth error code (here "invalid_client") is not actionable, so validation
        # must return the friendly reconnect message instead of leaking the code.
        make_session.return_value = _session([], post_responses=[_response(200, {"error": "invalid_client"})])

        is_valid, error = validate_credentials("us", "cid", "secret", "refresh")

        assert is_valid is False
        assert error == REFRESH_TOKEN_REJECTED_MESSAGE
        assert "invalid_client" not in (error or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_http_failure_is_not_valid(self, make_session: mock.MagicMock) -> None:
        forbidden = _response(403)
        forbidden.raise_for_status.side_effect = requests.HTTPError(
            "403 Client Error: Forbidden for url", response=mock.MagicMock()
        )
        make_session.return_value = _session([forbidden])

        assert validate_credentials("us", "cid", "secret", "refresh") == (False, None)


class TestZohoCRMSourceResponse:
    @pytest.mark.parametrize("endpoint", sorted(ZOHO_CRM_ENDPOINTS))
    def test_response_shape_per_endpoint(self, endpoint: str) -> None:
        response = zoho_crm_source(
            region="us",
            client_id="cid",
            client_secret="secret",
            refresh_token="refresh",
            endpoint=endpoint,
            api_version="v8",
            resumable_source_manager=FakeResumeManager(),
            logger=mock.MagicMock(),
        )

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [ZOHO_CRM_ENDPOINTS[endpoint].partition_key]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_items_are_lazy_until_iterated(self, make_session: mock.MagicMock) -> None:
        session = _session([_fields_response(1), _records_response([{"id": "1"}])])
        make_session.return_value = session

        response = zoho_crm_source(
            region="us",
            client_id="cid",
            client_secret="secret",
            refresh_token="refresh",
            endpoint="Leads",
            api_version="v8",
            resumable_source_manager=FakeResumeManager(),
            logger=mock.MagicMock(),
        )

        assert session.get.call_count == 0
        assert list(cast("Iterable[Any]", response.items())) == [[{"id": "1"}]]
