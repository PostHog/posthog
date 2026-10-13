from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.dynamics365 import (
    INVALID_ORGANIZATION_URL_ERROR,
    Dynamics365ConfigurationError,
    Dynamics365ResumeConfig,
    build_query_params,
    format_odata_datetime,
    normalize_organization_url,
    probe_credentials,
    resolve_incremental_field,
    strip_odata_annotations,
    token_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.settings import (
    DYNAMICS365_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.source import Dynamics365Source
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamics365 import (
    Dynamics365SourceConfig,
)

ORGANIZATION_URL = "https://contoso.crm.dynamics.com"
TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"
API_VERSION = "v9.2"
DATA_URL = f"{ORGANIZATION_URL}/api/data/{API_VERSION}"


def _page(rows: list[dict[str, Any]], next_link: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"value": rows}
    if next_link:
        body["@odata.nextLink"] = next_link
    return body


def _token_response(expires_in: int = 3599) -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "tok-1", "expires_in": expires_in, "token_type": "Bearer"})


def _driver(organization_url: str = ORGANIZATION_URL) -> SourceDriver:
    config = Dynamics365SourceConfig(
        organization_url=organization_url, tenant_id=TENANT_ID, client_id="cid", client_secret="sec"
    )
    return SourceDriver(Dynamics365Source(), config)


class TestNormalizeOrganizationUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://contoso.crm.dynamics.com", "https://contoso.crm.dynamics.com"),
            ("https://contoso.crm.dynamics.com/", "https://contoso.crm.dynamics.com"),
            ("contoso.crm.dynamics.com", "https://contoso.crm.dynamics.com"),
            ("  https://Contoso.CRM4.dynamics.com  ", "https://contoso.crm4.dynamics.com"),
            ("https://contoso.crm11.dynamics.com", "https://contoso.crm11.dynamics.com"),
            ("https://contoso.api.crm.dynamics.com", "https://contoso.api.crm.dynamics.com"),
            ("https://contoso.crm.dynamics.cn", "https://contoso.crm.dynamics.cn"),
            ("https://contoso.crm.microsoftdynamics.us", "https://contoso.crm.microsoftdynamics.us"),
            # A pasted deep link keeps only the origin, and a stray port is dropped — Dataverse is
            # only ever served over 443.
            ("https://contoso.crm.dynamics.com/main.aspx?pagetype=entitylist", "https://contoso.crm.dynamics.com"),
            ("https://contoso.crm.dynamics.com:8080", "https://contoso.crm.dynamics.com"),
        ],
    )
    def test_accepts_and_normalizes_dataverse_hosts(self, raw: str, expected: str) -> None:
        assert normalize_organization_url(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "http://contoso.crm.dynamics.com",  # plaintext
            "https://contoso.crm.dynamics.com.evil.test",
            "https://evil.test",
            "https://localhost",
            "https://169.254.169.254",
            "https://contoso.dynamics.com",  # missing the crm{n} region label
            "https://user:pass@evil.test/contoso.crm.dynamics.com",
        ],
    )
    def test_rejects_anything_else(self, raw: str) -> None:
        with pytest.raises(Dynamics365ConfigurationError) as error:
            normalize_organization_url(raw)
        assert str(error.value) == INVALID_ORGANIZATION_URL_ERROR


class TestTokenUrl:
    @pytest.mark.parametrize("tenant", [TENANT_ID, "contoso.onmicrosoft.com", "common"])
    def test_builds_entra_token_url(self, tenant: str) -> None:
        assert token_url(tenant) == f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    @pytest.mark.parametrize("tenant", ["", "  ", "../../evil", "tenant/oauth2", "tenant?x=1", "tenant#frag"])
    def test_rejects_values_that_could_escape_the_path(self, tenant: str) -> None:
        with pytest.raises(Dynamics365ConfigurationError):
            token_url(tenant)


class TestFormatOdataDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
            ("2024-01-02 03:04:05+00:00", "2024-01-02T03:04:05+00:00"),
            ("2024-01-02", "2024-01-02"),
        ],
    )
    def test_formats_odata_literals(self, value: Any, expected: str) -> None:
        assert format_odata_datetime(value) == expected

    @pytest.mark.parametrize("value", ["2024-01-02T03:04:05Z or 1 eq 1", "yesterday", "", "null"])
    def test_rejects_values_that_are_not_timestamps(self, value: str) -> None:
        with pytest.raises(Dynamics365ConfigurationError):
            format_odata_datetime(value)


class TestQueryParams:
    @pytest.mark.parametrize("requested, expected", [("modifiedon", "modifiedon"), ("createdon", "createdon")])
    def test_honours_the_users_cursor(self, requested: str, expected: str) -> None:
        assert resolve_incremental_field(DYNAMICS365_ENDPOINTS["Accounts"], requested) == expected

    @pytest.mark.parametrize("requested", [None, "", "name desc,modifiedon", "unknowncolumn"])
    def test_falls_back_to_the_default_cursor(self, requested: str | None) -> None:
        assert resolve_incremental_field(DYNAMICS365_ENDPOINTS["Accounts"], requested) == "modifiedon"

    def test_full_refresh_sends_no_filter_or_order(self) -> None:
        assert build_query_params(DYNAMICS365_ENDPOINTS["Accounts"], False, None, None) == {}

    def test_incremental_without_watermark_only_orders(self) -> None:
        params = build_query_params(DYNAMICS365_ENDPOINTS["Accounts"], True, None, "modifiedon")
        assert params == {"$orderby": "modifiedon asc"}

    def test_incremental_filters_and_orders_on_the_chosen_cursor(self) -> None:
        params = build_query_params(
            DYNAMICS365_ENDPOINTS["Opportunities"], True, datetime(2024, 3, 4, 5, 6, 7, tzinfo=UTC), "createdon"
        )
        assert params == {"$orderby": "createdon asc", "$filter": "createdon gt 2024-03-04T05:06:07Z"}

    def test_notes_selects_columns_without_the_attachment_body(self) -> None:
        params = build_query_params(DYNAMICS365_ENDPOINTS["Notes"], False, None, None)
        selected = params["$select"].split(",")
        assert "notetext" in selected
        assert "documentbody" not in selected

    @pytest.mark.parametrize("endpoint", [name for name in ENDPOINTS if name != "Notes"])
    def test_every_other_endpoint_returns_all_columns(self, endpoint: str) -> None:
        assert "$select" not in build_query_params(DYNAMICS365_ENDPOINTS[endpoint], False, None, None)


class TestStripOdataAnnotations:
    def test_drops_annotations_and_keeps_lookup_columns(self) -> None:
        row = {
            "@odata.etag": 'W/"1234"',
            "accountid": "a-1",
            "statecode@OData.Community.Display.V1.FormattedValue": "Active",
            "statecode": 0,
            "_primarycontactid_value": "c-1",
        }
        assert strip_odata_annotations(row) == {
            "accountid": "a-1",
            "statecode": 0,
            "_primarycontactid_value": "c-1",
        }


class TestDynamics365Source:
    def test_follows_next_link_until_absent(self) -> None:
        next_link = f"{DATA_URL}/accounts?$skiptoken=page2"
        result = _driver().run(
            "Accounts",
            [
                _token_response(),
                ScriptedResponse(json=_page([{"accountid": "a-1", "@odata.etag": 'W/"1"'}], next_link)),
                ScriptedResponse(json=_page([{"accountid": "a-2"}])),
            ],
        )

        assert result.raised is None
        assert [row["accountid"] for row in result.rows] == ["a-1", "a-2"]
        # The etag annotation never reaches the warehouse.
        assert all("@odata.etag" not in row for row in result.rows)
        assert result.urls[1:] == [f"{DATA_URL}/accounts", next_link]
        # State is saved only while a next link remains, after the page has been yielded.
        assert result.saved_states == [Dynamics365ResumeConfig(next_url=next_link)]
        assert result.committed_states == [Dynamics365ResumeConfig(next_url=next_link)]

    def test_resumes_from_the_saved_next_link(self) -> None:
        saved = f"{DATA_URL}/contacts?$skiptoken=page9"
        result = _driver().run(
            "Contacts",
            [_token_response(), ScriptedResponse(json=_page([{"contactid": "c-9"}]))],
            resume_state=Dynamics365ResumeConfig(next_url=saved),
        )

        assert result.raised is None
        assert result.urls[1:] == [saved]
        assert [row["contactid"] for row in result.rows] == ["c-9"]

    def test_empty_page_stops_without_saving(self) -> None:
        result = _driver().run("Leads", [_token_response(), ScriptedResponse(json=_page([]))])

        assert result.raised is None
        assert result.rows == []
        assert result.paths == [f"/{TENANT_ID}/oauth2/v2.0/token", "/api/data/v9.2/leads"]
        assert result.saved_states == []

    def test_a_response_without_a_value_collection_fails_loud(self) -> None:
        # Better to fail than to report a successful sync of zero rows.
        result = _driver().run(
            "Accounts", [_token_response(), ScriptedResponse(json={"error": {"code": "0x0", "message": "unexpected"}})]
        )

        assert isinstance(result.raised, ValueError)
        assert "matched nothing in the response" in str(result.raised)

    def test_off_host_next_link_is_refused(self) -> None:
        # A spoofed next link must not carry the access token to another host.
        result = _driver().run(
            "Accounts",
            [
                _token_response(),
                ScriptedResponse(json=_page([{"accountid": "a-1"}], "https://evil.test/api/data/v9.2/accounts")),
            ],
        )

        assert isinstance(result.raised, Exception)
        assert "allowed hosts" in str(result.raised)
        assert all(request.origin != "https://evil.test" for request in result.requests)

    def test_sends_odata_headers_and_page_size_preference(self) -> None:
        result = _driver().run("Accounts", [_token_response(), ScriptedResponse(json=_page([]))])

        assert result.raised is None
        assert result.requests[1].headers["authorization"] == "Bearer tok-1"
        # The OData negotiation headers ride the session the client builds.
        assert result.requests[1].headers["odata-version"] == "4.0"
        assert result.requests[1].headers["odata-maxversion"] == "4.0"
        assert result.requests[1].headers["prefer"] == "odata.maxpagesize=5000"

    def test_mints_one_environment_scoped_token_for_the_run(self) -> None:
        result = _driver().run(
            "Accounts",
            [
                _token_response(),
                ScriptedResponse(json=_page([{"accountid": "a-1"}], f"{DATA_URL}/accounts?$skiptoken=p2")),
                ScriptedResponse(json=_page([{"accountid": "a-2"}])),
            ],
        )

        assert result.raised is None
        token_requests = [request for request in result.requests if request.method == "POST"]
        assert len(token_requests) == 1
        assert token_requests[0].url == f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
        body = parse_qs((token_requests[0].body or b"").decode())
        assert body["grant_type"] == ["client_credentials"]
        assert body["scope"] == [f"{ORGANIZATION_URL}/.default"]
        assert body["client_secret"] == ["sec"]

    def test_remints_token_when_it_expires_mid_run(self) -> None:
        # expires_in=0 is the deterministic stand-in for a sync outliving the token lifetime.
        result = _driver().run(
            "Accounts",
            [
                _token_response(expires_in=0),
                ScriptedResponse(json=_page([{"accountid": "a-1"}], f"{DATA_URL}/accounts?$skiptoken=p2")),
                _token_response(expires_in=0),
                ScriptedResponse(json=_page([{"accountid": "a-2"}])),
            ],
        )

        assert result.raised is None
        assert [row["accountid"] for row in result.rows] == ["a-1", "a-2"]
        assert len([request for request in result.requests if request.method == "POST"]) == 2

    def test_incremental_run_filters_server_side(self) -> None:
        result = _driver().run(
            "Cases",
            [_token_response(), ScriptedResponse(json=_page([]))],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            incremental_field="modifiedon",
        )

        assert result.raised is None
        assert result.requests[1].param("$orderby") == "modifiedon asc"
        assert result.requests[1].param("$filter") == "modifiedon gt 2024-01-02T03:04:05Z"

    def test_next_link_carries_the_query_so_params_are_not_reapplied(self) -> None:
        next_link = f"{DATA_URL}/accounts?%24filter=modifiedon+gt+2024-01-02T03%3A04%3A05Z&%24skiptoken=p2"
        result = _driver().run(
            "Accounts",
            [
                _token_response(),
                ScriptedResponse(json=_page([{"accountid": "a-1"}], next_link)),
                ScriptedResponse(json=_page([])),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.urls[2] == next_link

    def test_rejects_an_environment_url_before_minting_a_token(self) -> None:
        result = _driver("https://evil.test").run("Accounts", [])

        assert isinstance(result.raised, Dynamics365ConfigurationError)
        assert result.requests == []

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_source_response_shape_per_endpoint(self, endpoint: str) -> None:
        config = DYNAMICS365_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_token_response(), ScriptedResponse(json=_page([]))])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        # Partitioned on the creation timestamp, which never changes for a record.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdon"]


class TestProbeCredentials:
    @pytest.mark.parametrize(
        "status, ok_statuses, expected",
        [
            (200, (200,), True),
            (403, (200,), False),
            (403, (200, 403), True),
            (401, (200, 403), False),
            (404, (200,), False),
            (500, (200,), False),
        ],
    )
    def test_maps_probe_status(self, status: int, ok_statuses: tuple[int, ...], expected: bool) -> None:
        def answer(request: RecordedRequest) -> ScriptedResponse:
            return _token_response() if request.method == "POST" else ScriptedResponse(status=status)

        with scripted_network(answer) as network:
            is_valid, reported = probe_credentials(
                ORGANIZATION_URL, TENANT_ID, "cid", "sec", API_VERSION, ok_statuses=ok_statuses
            )

        assert is_valid is expected
        assert reported == status
        assert network.requests_log[-1].path == "/api/data/v9.2/accounts"

    def test_reports_unreachable_environment(self) -> None:
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.method == "POST":
                return _token_response()
            raise ConnectionResetError("boom")

        with scripted_network(answer) as network:
            result = probe_credentials(ORGANIZATION_URL, TENANT_ID, "cid", "sec", API_VERSION)

        assert result == (False, None)
        assert {request.path for request in network.requests_log} == {
            f"/{TENANT_ID}/oauth2/v2.0/token",
            "/api/data/v9.2/accounts",
        }

    @pytest.mark.parametrize(
        "endpoint, expected_url",
        [
            (None, f"{DATA_URL}/accounts?$top=1&$select=accountid"),
            ("Opportunities", f"{DATA_URL}/opportunities?$top=1&$select=opportunityid"),
            # An unknown schema name falls back to the default probe rather than building a bad URL.
            ("NotATable", f"{DATA_URL}/accounts?$top=1&$select=accountid"),
        ],
    )
    def test_probes_one_row_of_the_requested_table(self, endpoint: str | None, expected_url: str) -> None:
        with scripted_network([_token_response(), ScriptedResponse()]) as network:
            result = probe_credentials(ORGANIZATION_URL, TENANT_ID, "cid", "sec", API_VERSION, endpoint)

        assert result == (True, 200)
        token_request, data_request = network.requests_log
        assert data_request.path == expected_url.split("?", 1)[0].removeprefix(ORGANIZATION_URL)
        assert data_request.param("$top") == "1"
        assert data_request.param("$select") == expected_url.split("$select=", 1)[1]
        assert parse_qs((token_request.body or b"").decode())["scope"] == [f"{ORGANIZATION_URL}/.default"]

    def test_probe_does_not_follow_redirect(self) -> None:
        with scripted_network(
            [_token_response(), ScriptedResponse(status=302, headers={"Location": "https://evil.test/"})]
        ) as network:
            result = probe_credentials(ORGANIZATION_URL, TENANT_ID, "cid", "sec", API_VERSION)

        assert result == (False, 302)
        assert all(request.origin != "https://evil.test" for request in network.requests_log)

    def test_raises_on_an_unusable_environment_url(self) -> None:
        with pytest.raises(Dynamics365ConfigurationError):
            probe_credentials("https://evil.test", TENANT_ID, "cid", "sec", API_VERSION)
