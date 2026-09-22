import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.dynamics365 import (
    INVALID_ORGANIZATION_URL_ERROR,
    Dynamics365ConfigurationError,
    Dynamics365ResumeConfig,
    build_query_params,
    dynamics365_source,
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

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
AUTH_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth.make_tracked_session"
)
PROBE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.dynamics365.make_tracked_session"
)

ORGANIZATION_URL = "https://contoso.crm.dynamics.com"
TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"
API_VERSION = "v9.2"
DATA_URL = f"{ORGANIZATION_URL}/api/data/{API_VERSION}"


def _response(payload: dict[str, Any], status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode()
    response.url = f"{DATA_URL}/accounts"
    return response


def _page(rows: list[dict[str, Any]], next_link: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"value": rows}
    if next_link:
        body["@odata.nextLink"] = next_link
    return body


def _token_response(expires_in: int = 3599) -> mock.MagicMock:
    # OAuth2Auth reads the token exchange body via response.raw.read (stream=True).
    response = mock.MagicMock()
    response.status_code = 200
    response.raw.read.return_value = json.dumps(
        {"access_token": "tok-1", "expires_in": expires_in, "token_type": "Bearer"}
    ).encode()
    return response


def _make_manager(resume_state: Dynamics365ResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock RESTClient session, snapshotting each request as it is prepared.

    ``request.params`` is one dict mutated across pages, so it has to be copied at prepare time. A
    real ``requests.Session`` does the preparing, so the OAuth2 token mint and Bearer header are
    genuinely applied.
    """
    session.headers = {}
    real_session = requests.Session()
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> requests.PreparedRequest:
        prepared = real_session.prepare_request(request)
        snapshots.append({"params": dict(request.params or {}), "url": prepared.url, "headers": dict(prepared.headers)})
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


def _source(
    endpoint: str,
    manager: mock.MagicMock,
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
    organization_url: str = ORGANIZATION_URL,
) -> SourceResponse:
    return dynamics365_source(
        organization_url=organization_url,
        tenant_id=TENANT_ID,
        client_id="cid",
        client_secret="sec",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        api_version=API_VERSION,
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        incremental_field=incremental_field,
    )


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
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_link_until_absent(self, MockSession: mock.MagicMock, MockAuth: mock.MagicMock) -> None:
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        next_link = f"{DATA_URL}/accounts?$skiptoken=page2"
        snapshots = _wire(
            session,
            [
                _response(_page([{"accountid": "a-1", "@odata.etag": 'W/"1"'}], next_link=next_link)),
                _response(_page([{"accountid": "a-2"}])),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("Accounts", manager))

        assert [row["accountid"] for row in rows] == ["a-1", "a-2"]
        # The etag annotation never reaches the warehouse.
        assert all("@odata.etag" not in row for row in rows)
        assert snapshots[0]["url"] == f"{DATA_URL}/accounts"
        assert snapshots[1]["url"] == next_link
        # State is saved only while a next link remains, after the page has been yielded.
        assert [call.args[0].next_url for call in manager.save_state.call_args_list] == [next_link]

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_the_saved_next_link(self, MockSession: mock.MagicMock, MockAuth: mock.MagicMock) -> None:
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        saved = f"{DATA_URL}/contacts?$skiptoken=page9"
        snapshots = _wire(session, [_response(_page([{"contactid": "c-9"}]))])

        rows = _rows(_source("Contacts", _make_manager(Dynamics365ResumeConfig(next_url=saved))))

        assert snapshots[0]["url"] == saved
        assert [row["contactid"] for row in rows] == ["c-9"]

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_without_saving(self, MockSession: mock.MagicMock, MockAuth: mock.MagicMock) -> None:
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(session, [_response(_page([]))])

        manager = _make_manager()
        assert _rows(_source("Leads", manager)) == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_a_response_without_a_value_collection_fails_loud(
        self, MockSession: mock.MagicMock, MockAuth: mock.MagicMock
    ) -> None:
        # Better to fail than to report a successful sync of zero rows.
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(session, [_response({"error": {"code": "0x0", "message": "unexpected"}})])

        with pytest.raises(ValueError, match="matched nothing in the response"):
            _rows(_source("Accounts", _make_manager()))

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_next_link_is_refused(self, MockSession: mock.MagicMock, MockAuth: mock.MagicMock) -> None:
        # A spoofed next link must not carry the access token to another host.
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(
            session,
            [
                _response(_page([{"accountid": "a-1"}], next_link="https://evil.test/api/data/v9.2/accounts")),
                _response(_page([{"accountid": "a-2"}])),
            ],
        )

        with pytest.raises(Exception, match="allowed hosts"):
            _rows(_source("Accounts", _make_manager()))

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_odata_headers_and_page_size_preference(
        self, MockSession: mock.MagicMock, MockAuth: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([]))])

        _rows(_source("Accounts", _make_manager()))

        assert snapshots[0]["headers"]["Authorization"] == "Bearer tok-1"
        # The OData negotiation headers ride the session the client builds.
        assert session.headers["OData-Version"] == "4.0"
        assert session.headers["OData-MaxVersion"] == "4.0"
        assert session.headers["Prefer"] == "odata.maxpagesize=5000"

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_mints_one_environment_scoped_token_for_the_run(
        self, MockSession: mock.MagicMock, MockAuth: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(
            session,
            [
                _response(_page([{"accountid": "a-1"}], next_link=f"{DATA_URL}/accounts?$skiptoken=p2")),
                _response(_page([{"accountid": "a-2"}])),
            ],
        )

        _rows(_source("Accounts", _make_manager()))

        assert MockAuth.return_value.post.call_count == 1
        assert (
            MockAuth.return_value.post.call_args.args[0]
            == f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
        )
        body = MockAuth.return_value.post.call_args.kwargs["data"]
        assert body["grant_type"] == "client_credentials"
        assert body["scope"] == f"{ORGANIZATION_URL}/.default"
        assert body["client_secret"] == "sec"

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_remints_token_when_it_expires_mid_run(self, MockSession: mock.MagicMock, MockAuth: mock.MagicMock) -> None:
        # expires_in=0 is the deterministic stand-in for a sync outliving the token lifetime.
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response(expires_in=0)
        _wire(
            session,
            [
                _response(_page([{"accountid": "a-1"}], next_link=f"{DATA_URL}/accounts?$skiptoken=p2")),
                _response(_page([{"accountid": "a-2"}])),
            ],
        )

        rows = _rows(_source("Accounts", _make_manager()))

        assert [row["accountid"] for row in rows] == ["a-1", "a-2"]
        assert MockAuth.return_value.post.call_count == 2

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_run_filters_server_side(self, MockSession: mock.MagicMock, MockAuth: mock.MagicMock) -> None:
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([]))])

        _rows(
            _source(
                "Cases",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
                incremental_field="modifiedon",
            )
        )

        assert snapshots[0]["params"] == {
            "$orderby": "modifiedon asc",
            "$filter": "modifiedon gt 2024-01-02T03:04:05Z",
        }

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_next_link_carries_the_query_so_params_are_not_reapplied(
        self, MockSession: mock.MagicMock, MockAuth: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        next_link = f"{DATA_URL}/accounts?%24filter=modifiedon+gt+2024-01-02T03%3A04%3A05Z&%24skiptoken=p2"
        snapshots = _wire(
            session,
            [_response(_page([{"accountid": "a-1"}], next_link=next_link)), _response(_page([]))],
        )

        _rows(
            _source(
                "Accounts",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            )
        )

        assert snapshots[1]["url"] == next_link

    def test_rejects_an_environment_url_before_minting_a_token(self) -> None:
        with pytest.raises(Dynamics365ConfigurationError):
            _source("Accounts", _make_manager(), organization_url="https://evil.test")

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_source_response_shape_per_endpoint(self, endpoint: str) -> None:
        config = DYNAMICS365_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

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
    @mock.patch(PROBE_SESSION_PATCH)
    def test_maps_probe_status(
        self, mock_session: mock.MagicMock, status: int, ok_statuses: tuple[int, ...], expected: bool
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)

        is_valid, reported = probe_credentials(
            ORGANIZATION_URL, TENANT_ID, "cid", "sec", API_VERSION, ok_statuses=ok_statuses
        )

        assert is_valid is expected
        assert reported == status

    @mock.patch(PROBE_SESSION_PATCH)
    def test_reports_unreachable_environment(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert probe_credentials(ORGANIZATION_URL, TENANT_ID, "cid", "sec", API_VERSION) == (False, None)

    @pytest.mark.parametrize(
        "endpoint, expected_url",
        [
            (None, f"{DATA_URL}/accounts?$top=1&$select=accountid"),
            ("Opportunities", f"{DATA_URL}/opportunities?$top=1&$select=opportunityid"),
            # An unknown schema name falls back to the default probe rather than building a bad URL.
            ("NotATable", f"{DATA_URL}/accounts?$top=1&$select=accountid"),
        ],
    )
    @mock.patch(PROBE_SESSION_PATCH)
    def test_probes_one_row_of_the_requested_table(
        self, mock_session: mock.MagicMock, endpoint: str | None, expected_url: str
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        probe_credentials(ORGANIZATION_URL, TENANT_ID, "cid", "sec", API_VERSION, endpoint)

        call = mock_session.return_value.get.call_args
        assert call.args[0] == expected_url
        assert call.kwargs["auth"].scopes == f"{ORGANIZATION_URL}/.default"
        assert call.kwargs["allow_redirects"] is False

    def test_raises_on_an_unusable_environment_url(self) -> None:
        with pytest.raises(Dynamics365ConfigurationError):
            probe_credentials("https://evil.test", TENANT_ID, "cid", "sec", API_VERSION)
