import json
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from requests.exceptions import HTTPError

from products.warehouse_sources.sources.sdk import RESTClientNonRetryableError, RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.sources.zoho_crm._config import ZohoCRMSourceConfig
from products.warehouse_sources.sources.zoho_crm.source import SCOPE_MISMATCH_MESSAGE, ZohoCRMSource
from products.warehouse_sources.sources.zoho_crm.zoho_crm import (
    CLIENT_REJECTED_MESSAGE,
    CLIENT_SECRET_REJECTED_MESSAGE,
    MAX_FIELDS_PER_REQUEST,
    MAX_PAGE,
    PAGE_SIZE,
    REFRESH_TOKEN_REJECTED_MESSAGE,
    ZohoCRMApiError,
    ZohoCRMAuthError,
    ZohoCRMClient,
    ZohoCRMResumeConfig,
    chunk_fields,
    format_modified_since,
    get_rows,
    list_custom_modules,
    readable_field_names,
    resolve_hosts,
    validate_credentials,
)

_TOKEN_PATH = "/oauth/v2/token"


def _response(status_code: int = 200, body: Optional[dict[str, Any]] = None) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body if body is not None else {})


def _undecodable_response(content: bytes) -> ScriptedResponse:
    """A 2xx whose body is not JSON."""
    return ScriptedResponse(body=content)


def _no_content_response(status_code: int) -> ScriptedResponse:
    """An empty-bodied Zoho response, as the real API sends for a read that matched nothing."""
    return ScriptedResponse(status=status_code, body=b"")


def _token_response(api_domain: str = "https://www.zohoapis.com") -> ScriptedResponse:
    return _response(200, {"access_token": "access-token", "api_domain": api_domain, "expires_in": 3600})


def _fields_response(count: int) -> ScriptedResponse:
    return _response(200, {"fields": [{"api_name": f"Field_{index}"} for index in range(count)]})


def _records_response(
    records: list[dict[str, Any]],
    more_records: bool = False,
    next_page_token: Optional[str] = None,
    data_key: str = "data",
) -> ScriptedResponse:
    info: dict[str, Any] = {"more_records": more_records, "per_page": PAGE_SIZE}
    if next_page_token is not None:
        info["next_page_token"] = next_page_token
    return _response(200, {data_key: records, "info": info})


def _script(
    data: Sequence[ScriptedResponse], tokens: Optional[Sequence[ScriptedResponse]] = None
) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer the token exchange from `tokens` and every other request from `data`, each in order."""
    token_queue = list(tokens) if tokens is not None else [_token_response()]
    data_queue = list(data)

    def respond(request: RecordedRequest) -> ScriptedResponse:
        queue = token_queue if request.path == _TOKEN_PATH else data_queue
        if not queue:
            raise UnexpectedRequest(f"the script has no answer left for {request.method} {request.url}")
        return queue.pop(0)

    return respond


def _client() -> ZohoCRMClient:
    return ZohoCRMClient("us", "cid", "secret", "refresh")


def _run(
    endpoint: str,
    data: Sequence[ScriptedResponse],
    resume_state: Optional[ZohoCRMResumeConfig] = None,
    tokens: Optional[Sequence[ScriptedResponse]] = None,
    **inputs: Any,
) -> DriveResult:
    driver = SourceDriver(
        ZohoCRMSource(),
        ZohoCRMSourceConfig(client_id="cid", client_secret="secret", refresh_token="refresh", region="us"),
    )
    return driver.run(endpoint, _script(data, tokens), resume_state=resume_state, **inputs)


def _crm_requests(result: DriveResult) -> list[RecordedRequest]:
    return [request for request in result.requests if request.path.startswith("/crm/")]


class TestResolveHosts:
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
    def test_token_response_api_domain_overrides_regional_default(self) -> None:
        with scripted_network(_script([], tokens=[_token_response("https://www.zohoapis.eu/")])):
            client = _client()

            client.mint_access_token()

        assert client.api_domain == "https://www.zohoapis.eu"

    def test_error_body_on_a_200_raises_auth_error(self) -> None:
        with scripted_network(_script([], tokens=[_response(200, {"error": "invalid_code"})])):
            client = _client()

            with pytest.raises(ZohoCRMAuthError, match="invalid_code"):
                client.mint_access_token()

    def test_non_json_token_body_is_non_retryable(self) -> None:
        with scripted_network(_script([], tokens=[_undecodable_response(b"<html><body>Sign in</body></html>")])):
            client = _client()

            with pytest.raises(RESTClientNonRetryableError):
                client.mint_access_token()

    def test_remints_once_on_401_and_replays_the_request(self) -> None:
        with scripted_network(
            _script([_response(401), _response(200, {"data": []})], tokens=[_token_response(), _token_response()])
        ) as network:
            response = _client().get("/crm/v8/Leads")

        assert response.status_code == 200
        assert [request.path for request in network.requests_log].count(_TOKEN_PATH) == 2

    def test_session_disables_sample_capture_and_redacts_credentials(self) -> None:
        # Reverting capture=False would upload raw CRM records (contacts, notes, emails) and the
        # minted access token to the shared HTTP sample-capture prefix.
        with scripted_network(_script([])) as network:
            ZohoCRMClient("us", "cid", "secret-value", "refresh-value")

        assert network.session_options == [{"redact_values": ("secret-value", "refresh-value"), "capture": False}]


class TestReadableFieldNames:
    def test_skips_fields_the_api_never_returns(self) -> None:
        fields = _response(
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
        with scripted_network(_script([fields])):
            names = readable_field_names(_client(), "v8", "Leads")

        assert names == ["Last_Name", "No_View_Type"]

    @pytest.mark.parametrize("status_code", [204, 304])
    def test_no_content_metadata_yields_no_projection(self, status_code: int) -> None:
        with scripted_network(_script([_no_content_response(status_code)])):
            assert readable_field_names(_client(), "v8", "Leads") == []

    def test_empty_metadata_body_yields_no_projection(self) -> None:
        with scripted_network(_script([_undecodable_response(b"")])):
            assert readable_field_names(_client(), "v8", "Leads") == []

    @pytest.mark.parametrize(
        ("body", "expected_detail"),
        [
            (
                {"code": "INVALID_MODULE", "message": "the module name given seems to be invalid"},
                "INVALID_MODULE: the module name given seems to be invalid",
            ),
            ({"code": "INVALID_MODULE"}, "INVALID_MODULE"),
            ({"message": "no code here"}, "no code here"),
        ],
    )
    def test_structured_400_surfaces_zohos_code_and_message(self, body: dict[str, Any], expected_detail: str) -> None:
        # A bare raise_for_status() discards this body, so an org missing an edition-gated
        # module (e.g. Vendors, without Zoho's Inventory feature) is indistinguishable from any
        # other 400 — see the should_sync_default comment in settings.py.
        with scripted_network(_script([_response(400, body)])):
            with pytest.raises(ZohoCRMApiError, match=expected_detail):
                readable_field_names(_client(), "v8", "Vendors")

    @pytest.mark.parametrize(
        ("call", "responses"),
        [
            pytest.param(lambda: readable_field_names(_client(), "v8", "Leads"), [], id="fields_metadata"),
            pytest.param(lambda: list_custom_modules(_client(), "v8"), [], id="modules_metadata"),
            pytest.param(
                lambda: list(
                    get_rows(
                        _client(), "v8", "Leads", mock.MagicMock(**{"can_resume.return_value": False}), mock.MagicMock()
                    )
                ),
                [_fields_response(1)],
                id="records_page",
            ),
        ],
    )
    @pytest.mark.parametrize("body", [b"not json", b""])
    def test_400_without_a_structured_body_stays_a_plain_http_error(
        self, call: Callable[[], Any], responses: list[ScriptedResponse], body: bytes
    ) -> None:
        with scripted_network(_script([*responses, ScriptedResponse(status=400, body=body)])):
            with pytest.raises(HTTPError) as ctx:
                call()

        assert not isinstance(ctx.value, ZohoCRMApiError)
        # A self-referencing cause sends Temporal's failure converter into a RecursionError.
        assert ctx.value.__cause__ is not ctx.value

    def test_invalid_module_error_matches_get_non_retryable_errors(self) -> None:
        body = {"code": "INVALID_MODULE", "message": "the module name given seems to be invalid"}
        with scripted_network(_script([_response(400, body)])):
            with pytest.raises(ZohoCRMApiError) as ctx:
                readable_field_names(_client(), "v8", "Vendors")

        non_retryable = ZohoCRMSource().get_non_retryable_errors()
        assert any(pattern.lower() in str(ctx.value).lower() for pattern in non_retryable)

    def test_no_permission_error_matches_get_non_retryable_errors(self) -> None:
        # Zoho answers this for a module the connected user's profile lacks access to, even
        # when the module itself is enabled for the org (unlike INVALID_MODULE above).
        body = {"code": "NO_PERMISSION", "message": "permission denied to access the module"}
        with scripted_network(_script([_response(400, body)])):
            with pytest.raises(ZohoCRMApiError) as ctx:
                readable_field_names(_client(), "v8", "Products")

        non_retryable = ZohoCRMSource().get_non_retryable_errors()
        assert any(pattern.lower() in str(ctx.value).lower() for pattern in non_retryable)

    def test_scope_mismatch_names_the_scope_instead_of_blaming_the_token(self) -> None:
        # Zoho answers a missing settings scope with a 401, which the client re-mints once for.
        body = {"code": "OAUTH_SCOPE_MISMATCH", "message": "invalid oauth scope to access this URL"}
        result = _run(
            "Territories", [_response(401, body), _response(401, body)], tokens=[_token_response(), _token_response()]
        )

        assert isinstance(result.raised, ZohoCRMApiError)
        error = str(result.raised).lower()
        friendly = [
            message
            for pattern, message in ZohoCRMSource().get_non_retryable_errors().items()
            if pattern.lower() in error
        ]
        assert friendly[0] == SCOPE_MISMATCH_MESSAGE


class TestGetRows:
    def test_incremental_sync_filters_and_sorts_on_the_cursor_field(self) -> None:
        result = _run(
            "Contacts",
            [_fields_response(1), _records_response([{"id": "1"}])],
            incremental_field="Modified_Time",
            db_incremental_field_last_value=datetime(2024, 6, 1, tzinfo=UTC),
        )

        records_request = _crm_requests(result)[1]
        assert records_request.headers["if-modified-since"] == "2024-06-01T00:00:00+00:00"
        assert records_request.param("sort_by") == "Modified_Time"

    @pytest.mark.parametrize("status_code", [204, 304])
    def test_no_content_module_response_yields_nothing(self, status_code: int) -> None:
        result = _run("Leads", [_fields_response(1), _no_content_response(status_code)])

        assert result.raised is None
        assert result.items == []

    def test_stops_at_the_page_window_when_no_token_is_offered(self) -> None:
        pages = [_records_response([{"id": str(page)}], more_records=True) for page in range(MAX_PAGE + 2)]
        logger = mock.MagicMock()

        result = _run("Leads", [_fields_response(1), *pages], logger=logger)

        assert len(result.items) == MAX_PAGE
        logger.warning.assert_called_once()

    def test_resumes_from_the_saved_page_token(self) -> None:
        result = _run(
            "Leads",
            [_fields_response(1), _records_response([{"id": "9"}])],
            resume_state=ZohoCRMResumeConfig(page=12, page_tokens=["tok-11"]),
        )

        assert result.items == [[{"id": "9"}]]
        assert _crm_requests(result)[1].param("page_token") == "tok-11"

    def test_restarts_when_saved_tokens_no_longer_match_the_field_slices(self) -> None:
        # Two slices now, but the checkpoint only carries one token — the tokens are unusable.
        result = _run(
            "Leads",
            [
                _fields_response(MAX_FIELDS_PER_REQUEST + 1),
                _records_response([{"id": "1"}]),
                _records_response([{"id": "1"}]),
            ],
            resume_state=ZohoCRMResumeConfig(page=25, page_tokens=["stale"]),
        )

        assert _crm_requests(result)[1].param("page") == "1"
        assert _crm_requests(result)[1].param("page_token") is None

    @pytest.mark.parametrize(
        ("endpoint", "data_key", "path", "type_param"),
        [
            ("Users", "users", "/crm/v8/users", "AllUsers"),
            ("Territories", "territories", "/crm/v8/settings/territories", None),
        ],
    )
    def test_settings_endpoints_skip_field_metadata_and_read_their_own_envelope(
        self, endpoint: str, data_key: str, path: str, type_param: Optional[str]
    ) -> None:
        result = _run(endpoint, [_records_response([{"id": "x1"}], data_key=data_key)])

        requests_made = _crm_requests(result)
        assert result.items == [[{"id": "x1"}]]
        assert len(requests_made) == 1
        assert requests_made[0].path == path
        assert requests_made[0].param("type") == type_param
        assert requests_made[0].param("sort_by") is None
        assert requests_made[0].param("fields") is None

    @pytest.mark.parametrize(
        ("endpoint", "module_api_name"),
        [
            ("Custom_Projects", "Projects"),
            ("Appointments", "Appointments__s"),
            ("Services", "Services__s"),
        ],
    )
    def test_modules_named_apart_from_their_table_read_through_get_records(
        self, endpoint: str, module_api_name: str
    ) -> None:
        result = _run(
            endpoint,
            [_fields_response(1), _records_response([{"id": "p1"}])],
            incremental_field="Modified_Time",
            db_incremental_field_last_value=datetime(2024, 6, 1, tzinfo=UTC),
        )

        fields_request, records_request = _crm_requests(result)
        assert result.items == [[{"id": "p1"}]]
        assert fields_request.param("module") == module_api_name
        assert records_request.path == f"/crm/v8/{module_api_name}"
        assert records_request.headers["if-modified-since"] == "2024-06-01T00:00:00+00:00"
        assert records_request.param("sort_by") == "Modified_Time"

    def test_empty_records_body_stops_pagination_without_crashing(self) -> None:
        result = _run(
            "Leads",
            [_fields_response(1), _undecodable_response(b"")],
            resume_state=ZohoCRMResumeConfig(page=1, page_tokens=[]),
        )

        assert result.raised is None
        assert result.items == []
        assert result.final_state is None

    def test_non_json_records_body_is_non_retryable(self) -> None:
        result = _run(
            "Leads",
            [_fields_response(1), _undecodable_response(b"<!DOCTYPE html><html><body>Sign in</body></html>")],
        )

        # The request URL carries a query string, which holds the page token and the field list.
        assert isinstance(result.raised, RESTClientNonRetryableError)
        assert str(result.raised) == "Non-JSON response from https://www.zohoapis.com/crm/v8/Leads"

    def test_truncated_records_body_stays_retryable(self) -> None:
        result = _run("Leads", [_fields_response(1), _undecodable_response(b'{"data": [{"id": "1"}')])

        assert isinstance(result.raised, RESTClientRetryableError)

    def test_structured_400_on_records_page_surfaces_zohos_detail(self) -> None:
        # A module can be disabled between the fields-metadata call and the first records page
        # of the same sync, so this call site needs the same detail as readable_field_names.
        body = {"code": "INVALID_MODULE", "message": "the module name given seems to be invalid"}
        result = _run("Vendors", [_fields_response(1), _response(400, body)])

        assert isinstance(result.raised, ZohoCRMApiError)
        assert "INVALID_MODULE: the module name given seems to be invalid" in str(result.raised)


class TestPipelines:
    def test_reads_the_pipelines_of_every_deals_layout(self) -> None:
        result = _run(
            "Pipelines",
            [
                _response(200, {"layouts": [{"id": "L1"}, {"id": "L2"}, {"name": "no id"}]}),
                _response(200, {"pipeline": [{"id": "P1", "maps": []}, {"id": "P2", "maps": []}]}),
                _no_content_response(204),
            ],
        )

        requests_made = _crm_requests(result)
        assert result.raised is None
        assert result.rows == [
            {"id": "P1", "maps": [], "layout_id": "L1"},
            {"id": "P2", "maps": [], "layout_id": "L1"},
        ]
        assert requests_made[0].path == "/crm/v8/settings/layouts"
        assert requests_made[0].param("module") == "Deals"
        assert [request.param("layout_id") for request in requests_made[1:]] == ["L1", "L2"]
        assert result.response is not None and result.response.primary_keys == ["layout_id", "id"]


def _deals_response(ids: list[str], more_records: bool = False, next_page_token: Optional[str] = None):
    return _records_response([{"id": deal_id} for deal_id in ids], more_records, next_page_token)


def _timeline_response(ids: list[str], next_page_token: Optional[str] = None) -> ScriptedResponse:
    info = {"more_records": next_page_token is not None, "next_page_token": next_page_token}
    return _response(200, {"__timeline": [{"id": entry_id} for entry_id in ids], "info": info})


class TestDealTimeline:
    def test_walks_every_timeline_page_of_every_deal(self) -> None:
        result = _run(
            "Deal_Timeline",
            [
                _deals_response(["D1", "D2"], more_records=True, next_page_token="deals-2"),
                _timeline_response(["t1"], next_page_token="tl-2"),
                _timeline_response(["t2"]),
                _no_content_response(204),
                _deals_response(["D3"]),
                _timeline_response(["t3"]),
            ],
        )

        requests_made = _crm_requests(result)
        assert result.raised is None
        assert result.rows == [
            {"id": "t1", "deal_id": "D1"},
            {"id": "t2", "deal_id": "D1"},
            {"id": "t3", "deal_id": "D3"},
        ]
        assert [request.path for request in requests_made] == [
            "/crm/v8/Deals",
            "/crm/v8/Deals/D1/__timeline",
            "/crm/v8/Deals/D1/__timeline",
            "/crm/v8/Deals/D2/__timeline",
            "/crm/v8/Deals",
            "/crm/v8/Deals/D3/__timeline",
        ]
        # Zoho refuses per_page next to page_token on the timeline.
        assert (requests_made[2].param("page_token"), requests_made[2].param("per_page")) == ("tl-2", None)
        assert requests_made[4].param("page_token") == "deals-2"
        assert result.final_state is None
        assert result.response is not None
        assert result.response.primary_keys == ["deal_id", "id"]
        assert result.response.sort_mode is None

    def test_incremental_run_narrows_deals_and_entries_to_the_watermark(self) -> None:
        result = _run(
            "Deal_Timeline",
            [_deals_response(["D1"]), _timeline_response(["t1"])],
            incremental_field="audited_time",
            db_incremental_field_last_value=datetime(2024, 6, 1, tzinfo=UTC),
        )

        deals_request, timeline_request = _crm_requests(result)
        assert deals_request.headers["if-modified-since"] == "2024-06-01T00:00:00+00:00"
        filters = json.loads(timeline_request.param("filters") or "")
        assert filters["field"] == {"api_name": "audited_time"}
        assert filters["comparator"] == "between"
        assert filters["value"][0] == "2024-06-01T00:00:00+00:00"

    def test_full_refresh_reads_every_entry(self) -> None:
        result = _run("Deal_Timeline", [_deals_response(["D1"]), _timeline_response(["t1"])])

        deals_request, timeline_request = _crm_requests(result)
        assert "if-modified-since" not in deals_request.headers
        assert timeline_request.param("filters") is None

    @pytest.mark.parametrize(
        ("deal_ids", "saved_token", "expected_calls"),
        [
            (["998", "999", "1000"], "tl-999", [("999", "tl-999"), ("1000", None)]),
            (["999", "1000"], "tl-999", [("999", "tl-999"), ("1000", None)]),
            (["998", "999", "1000"], "", [("1000", None)]),
            (["998", "1000"], "tl-999", [("1000", None)]),
        ],
        ids=["inside_deal", "earlier_deal_deleted", "deal_finished", "saved_deal_deleted"],
    )
    def test_resumes_at_the_saved_deal(
        self, deal_ids: list[str], saved_token: str, expected_calls: list[tuple[str, Optional[str]]]
    ) -> None:
        result = _run(
            "Deal_Timeline",
            [_deals_response(deal_ids), *[_timeline_response([f"t{index}"]) for index in range(len(expected_calls))]],
            resume_state=ZohoCRMResumeConfig(page=1, parent_id="999", child_page_token=saved_token),
        )

        timeline_calls = [
            (request.path.split("/")[-2], request.param("page_token")) for request in _crm_requests(result)[1:]
        ]
        assert result.raised is None
        assert timeline_calls == expected_calls

    def test_saves_the_position_inside_a_deal_before_yielding_its_page(self) -> None:
        result = _run(
            "Deal_Timeline",
            [_deals_response(["D1", "D2"]), _timeline_response(["t1"], next_page_token="tl-2"), _timeline_response([])],
        )

        assert result.saved_states[0] == ZohoCRMResumeConfig(page=1, parent_id="D1", child_page_token="tl-2")
        assert result.saved_states[1] == ZohoCRMResumeConfig(page=1, parent_id="D1")


def _contact_roles_response(ids: list[str]) -> ScriptedResponse:
    rows = [{"id": contact_id, "Contact_Role": {"id": f"role-{contact_id}", "name": "Evaluator"}} for contact_id in ids]
    return _records_response(rows)


class TestDealContactRoles:
    def test_reads_the_contact_roles_of_every_deal(self) -> None:
        result = _run(
            "Deal_Contact_Roles",
            [
                _deals_response(["D1", "D2"], more_records=True, next_page_token="deals-2"),
                _contact_roles_response(["C1", "C2"]),
                _no_content_response(204),
                _deals_response(["D3"]),
                _contact_roles_response(["C1"]),
            ],
        )

        requests_made = _crm_requests(result)
        assert result.raised is None
        assert [(row["deal_id"], row["id"]) for row in result.rows] == [("D1", "C1"), ("D1", "C2"), ("D3", "C1")]
        assert [request.path for request in requests_made] == [
            "/crm/v8/Deals",
            "/crm/v8/Deals/D1/Contact_Roles",
            "/crm/v8/Deals/D2/Contact_Roles",
            "/crm/v8/Deals",
            "/crm/v8/Deals/D3/Contact_Roles",
        ]
        # Zoho rejects a contact roles request that names no fields.
        role_requests = [request for request in requests_made if request.path.endswith("/Contact_Roles")]
        assert [request.param("fields") for request in role_requests] == ["Full_Name,Email"] * 3
        assert "if-modified-since" not in requests_made[0].headers
        assert result.final_state is None
        assert result.response is not None
        assert result.response.primary_keys == ["deal_id", "id"]


class TestValidateCredentials:
    def test_valid_when_the_modules_probe_succeeds(self) -> None:
        with scripted_network(_script([_response(200, {"modules": []})])):
            assert validate_credentials("us", "cid", "secret", "refresh") == (True, None)

    def test_unknown_region_is_rejected_without_a_request(self) -> None:
        is_valid, error = validate_credentials("mars", "cid", "secret", "refresh")

        assert is_valid is False
        assert error is not None and "mars" in error

    @pytest.mark.parametrize(
        ("error_code", "expected"),
        [
            ("invalid_code", REFRESH_TOKEN_REJECTED_MESSAGE),
            ("invalid_client", CLIENT_REJECTED_MESSAGE),
            ("invalid_client_secret", CLIENT_SECRET_REJECTED_MESSAGE),
        ],
    )
    def test_token_rejection_gives_actionable_copy(self, error_code: str, expected: str) -> None:
        with scripted_network(_script([], tokens=[_response(200, {"error": error_code})])):
            is_valid, error = validate_credentials("us", "cid", "secret", "refresh")

        assert is_valid is False
        assert error == expected
        assert error_code not in (error or "")

    def test_http_failure_is_not_valid(self) -> None:
        with scripted_network(_script([_response(403)])):
            assert validate_credentials("us", "cid", "secret", "refresh") == (False, None)


class TestZohoCRMSourceResponse:
    def test_items_are_lazy_until_iterated(self) -> None:
        source = ZohoCRMSource()
        config = ZohoCRMSourceConfig(client_id="cid", client_secret="secret", refresh_token="refresh", region="us")
        inputs = source_inputs("Leads")

        with scripted_network(_script([_fields_response(1), _records_response([{"id": "1"}])])) as network:
            response = source.source_for_pipeline(config, source.get_resumable_source_manager(inputs), inputs)

            assert network.requests_log == []
            items = response.items()
            assert isinstance(items, Iterable)
            assert list(items) == [[{"id": "1"}]]
