import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, unquote_plus, urlparse

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.dynamics_365_business_central import (
    BUSINESS_CENTRAL_HOST,
    BusinessCentralConfigurationError,
    Dynamics365BusinessCentralResumeConfig,
    build_base_url,
    build_incremental_params,
    dynamics_365_business_central_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.settings import (
    BUSINESS_CENTRAL_ENDPOINTS,
    ENDPOINTS,
    BusinessCentralEndpoint,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.dynamics_365_business_central"
SESSION_PATCH = f"{MODULE}.make_tracked_session"
# OAuth2Auth mints its Entra token through its own session, built inside the framework auth module.
AUTH_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth.make_tracked_session"
)

TENANT = "contoso.onmicrosoft.com"
ENVIRONMENT = "production"
API_VERSION = "v2.0"
API_ROOT = f"https://{BUSINESS_CENTRAL_HOST}/v2.0/{TENANT}/{ENVIRONMENT}/api/{API_VERSION}"
# The company enumeration carries no query string, so route on the bare path.
COMPANIES_ROUTE = f"{API_ROOT}/companies"


def _response(payload: Any, status_code: int = 200, url: str = f"{API_ROOT}/companies") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(payload).encode()
    resp.url = url
    resp.reason = "Error"
    return resp


def _page(rows: list[dict[str, Any]], next_link: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"@odata.context": f"{API_ROOT}/$metadata", "value": rows}
    if next_link:
        payload["@odata.nextLink"] = next_link
    return payload


def _token_payload(token: str = "entra-token", expires_in: int = 3599) -> bytes:
    return json.dumps({"access_token": token, "expires_in": expires_in, "token_type": "Bearer"}).encode()


def _wire_token(mock_auth_session: mock.MagicMock, body: bytes = b"", status_code: int = 200) -> mock.MagicMock:
    """Stub the Entra ID token exchange. `OAuth2Auth` streams the body, so `raw.read` supplies it."""
    response = mock.MagicMock()
    response.status_code = status_code
    response.raw.read.return_value = body or _token_payload()
    mock_auth_session.return_value.post.return_value = response
    return mock_auth_session.return_value


def _wire(session: mock.MagicMock, routes: list[tuple[str, Response]]) -> list[str]:
    """Dispatch each request to the first still-unconsumed route whose substring appears in the
    fully-prepared URL. Real `Request.prepare()` builds the URL and applies the OAuth2 auth (which
    mints the token), so fan-out, pagination and auth all route deterministically. Returns the URLs
    sent, in order."""
    session.headers = {}
    sent_urls: list[str] = []
    remaining = list(routes)

    def _dispatch(prepared: Any) -> Response:
        sent_urls.append(prepared.url)
        for i, (substr, response) in enumerate(remaining):
            if substr in prepared.url:
                remaining.pop(i)
                return response
        raise AssertionError(f"no route for {prepared.url}")

    def _prepare(request: Any) -> Any:
        return request.prepare()

    def _send(prepared: Any, **kwargs: Any) -> Response:
        return _dispatch(prepared)

    def _get(url: str, **kwargs: Any) -> Response:
        prepared = requests.Request("GET", url, params=kwargs.get("params"), auth=kwargs.get("auth")).prepare()
        return _dispatch(prepared)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    session.get.side_effect = _get
    return sent_urls


def _make_manager(resume_state: Dynamics365BusinessCentralResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return dynamics_365_business_central_source(
        tenant_id=TENANT,
        environment=ENVIRONMENT,
        client_id="client-id",
        client_secret="client-secret",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        api_version=API_VERSION,
        **kwargs,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


class TestBuildBaseUrl:
    def test_builds_per_tenant_per_environment_root(self) -> None:
        assert build_base_url(TENANT, ENVIRONMENT, API_VERSION) == API_ROOT

    @pytest.mark.parametrize(
        "tenant_id, environment, api_version",
        [
            # A path segment that escapes the API root would retarget the credentialed request.
            ("../../evil", ENVIRONMENT, API_VERSION),
            ("tenant/extra", ENVIRONMENT, API_VERSION),
            ("tenant id", ENVIRONMENT, API_VERSION),
            ("", ENVIRONMENT, API_VERSION),
            (TENANT, "prod/../admin", API_VERSION),
            (TENANT, "prod uction", API_VERSION),
            (TENANT, "", API_VERSION),
            (TENANT, ENVIRONMENT, "beta"),
            (TENANT, ENVIRONMENT, "../v1.0"),
        ],
    )
    def test_rejects_path_escaping_values(self, tenant_id: str, environment: str, api_version: str) -> None:
        with pytest.raises(BusinessCentralConfigurationError):
            build_base_url(tenant_id, environment, api_version)


class TestBuildIncrementalParams:
    @pytest.mark.parametrize(
        "last_value, expected",
        [
            (datetime(2026, 6, 1, 12, 30, 15, tzinfo=UTC), "lastModifiedDateTime gt 2026-06-01T12:30:15Z"),
            (datetime(2026, 6, 1, 12, 30, 15), "lastModifiedDateTime gt 2026-06-01T12:30:15Z"),
            (date(2026, 6, 1), "lastModifiedDateTime gt 2026-06-01T00:00:00Z"),
            ("2026-06-01T12:30:15Z", "lastModifiedDateTime gt 2026-06-01T12:30:15Z"),
        ],
    )
    def test_formats_watermark_as_odata_literal(self, last_value: Any, expected: str) -> None:
        params = build_incremental_params(BUSINESS_CENTRAL_ENDPOINTS["customers"], True, last_value)
        assert params == {"$filter": expected}

    def test_honors_the_users_chosen_cursor_field(self) -> None:
        params = build_incremental_params(
            BUSINESS_CENTRAL_ENDPOINTS["generalLedgerEntries"],
            True,
            datetime(2026, 6, 1, tzinfo=UTC),
            incremental_field="postingDate",
        )
        assert params == {"$filter": "postingDate gt 2026-06-01T00:00:00Z"}

    @pytest.mark.parametrize("chosen_field", ["lastModifiedDateTime eq 1 or 1", "id) and (1", ""])
    def test_falls_back_when_the_chosen_field_is_not_a_bare_property(self, chosen_field: str) -> None:
        # The field is interpolated into an OData $filter, so a value carrying filter syntax must
        # not reach the query.
        params = build_incremental_params(
            BUSINESS_CENTRAL_ENDPOINTS["customers"],
            True,
            datetime(2026, 6, 1, tzinfo=UTC),
            incremental_field=chosen_field,
        )
        assert params == {"$filter": "lastModifiedDateTime gt 2026-06-01T00:00:00Z"}

    @pytest.mark.parametrize(
        "endpoint, should_use_incremental_field, last_value",
        [
            # First sync: no watermark yet.
            ("customers", True, None),
            ("customers", False, datetime(2026, 6, 1, tzinfo=UTC)),
            # Full-refresh endpoints never window, even with a watermark present.
            ("salesInvoiceLines", True, datetime(2026, 6, 1, tzinfo=UTC)),
            ("companies", True, datetime(2026, 6, 1, tzinfo=UTC)),
            # An unparseable stored watermark must not produce a broken $filter.
            ("customers", True, "not-a-date"),
        ],
    )
    def test_no_filter_without_a_usable_watermark(
        self, endpoint: str, should_use_incremental_field: bool, last_value: Any
    ) -> None:
        assert (
            build_incremental_params(BUSINESS_CENTRAL_ENDPOINTS[endpoint], should_use_incremental_field, last_value)
            == {}
        )


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [(200, True), (401, False), (403, False), (404, False), (429, False), (500, False)],
    )
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_status_mapping(
        self,
        mock_session: mock.MagicMock,
        mock_auth_session: mock.MagicMock,
        status_code: int,
        expected_valid: bool,
    ) -> None:
        _wire_token(mock_auth_session)
        _wire(mock_session.return_value, [("/companies", _response({"value": []}, status_code=status_code))])

        valid, message = validate_credentials(TENANT, ENVIRONMENT, "client-id", "client-secret", API_VERSION)

        assert valid is expected_valid
        assert (message is None) is expected_valid

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_sends_the_minted_bearer_token(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        auth_session = _wire_token(mock_auth_session, _token_payload("minted-token"))
        _wire(mock_session.return_value, [("/companies", _response({"value": []}))])

        assert validate_credentials(TENANT, ENVIRONMENT, "client-id", "client-secret", API_VERSION) == (True, None)
        token_body = auth_session.post.call_args.kwargs["data"]
        assert token_body["grant_type"] == "client_credentials"
        assert token_body["scope"] == f"https://{BUSINESS_CENTRAL_HOST}/.default"
        assert token_body["client_secret"] == "client-secret"
        assert auth_session.post.call_args.args[0] == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_entra_token_rejection_is_reported_without_the_internal_marker(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        _wire_token(
            mock_auth_session,
            json.dumps({"error": "invalid_client", "error_description": "AADSTS7000215"}).encode(),
            status_code=401,
        )
        _wire(mock_session.return_value, [])

        valid, message = validate_credentials(TENANT, ENVIRONMENT, "client-id", "client-secret", API_VERSION)

        assert valid is False
        assert message is not None
        assert "invalid_client" in message
        assert "oauth2_token_config_error" not in message

    @mock.patch(SESSION_PATCH)
    def test_bad_environment_name_fails_before_any_request(self, mock_session: mock.MagicMock) -> None:
        valid, message = validate_credentials(TENANT, "prod/../admin", "client-id", "client-secret", API_VERSION)

        assert valid is False
        assert message is not None and "environment name" in message
        mock_session.assert_not_called()

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_transport_failure_is_not_valid(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        _wire_token(mock_auth_session)
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        valid, message = validate_credentials(TENANT, ENVIRONMENT, "client-id", "client-secret", API_VERSION)

        assert valid is False
        assert message is not None and "Could not reach Business Central" in message


class TestGetRows:
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_companies_is_top_level_and_strips_odata_annotations(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        _wire_token(mock_auth_session)
        urls = _wire(
            mock_session.return_value,
            [("/companies", _response(_page([{"id": "c-1", "name": "cronus", "@odata.etag": 'W/"1"'}])))],
        )

        manager = _make_manager()
        rows = _rows(_source("companies", manager))

        assert rows == [{"id": "c-1", "name": "cronus"}]
        assert len(urls) == 1
        assert urls[0].startswith(f"{API_ROOT}/companies")

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_row_bodies_are_kept_out_of_http_sample_capture(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        # Rows carry ledger, payment, bank-account and tax fields the name-based scrubbers can't
        # recognise, so the sync session must opt out of body capture. Dropping `capture=False`
        # would persist raw financial records to the HTTP sample store.
        _wire_token(mock_auth_session)
        _wire(mock_session.return_value, [("/companies", _response(_page([])))])

        _rows(_source("companies", _make_manager()))

        assert mock_session.call_args.kwargs["capture"] is False
        assert mock_session.call_args.kwargs["redact_values"] == ("client-secret",)

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_company_scoped_endpoint_fans_out_and_stamps_the_company(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        _wire_token(mock_auth_session)
        urls = _wire(
            mock_session.return_value,
            [
                (
                    COMPANIES_ROUTE,
                    _response(_page([{"id": "c-1", "name": "cronus"}, {"id": "c-2", "name": "acme"}])),
                ),
                ("companies(c-1)/customers", _response(_page([{"id": "cust-1"}]))),
                ("companies(c-2)/customers", _response(_page([{"id": "cust-2"}]))),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("customers", manager))

        assert rows == [
            {"id": "cust-1", "company_id": "c-1", "company_name": "cronus"},
            {"id": "cust-2", "company_id": "c-2", "company_name": "acme"},
        ]
        # Single-hop fan-out stays resumable: per-company progress is checkpointed.
        assert manager.save_state.called
        assert "completed" in manager.save_state.call_args.args[0].paginator_state
        assert len(urls) == 3

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_pagination_follows_odata_next_link_and_terminates(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        _wire_token(mock_auth_session)
        next_link = f"{API_ROOT}/companies(c-1)/items?$skiptoken=abc"
        urls = _wire(
            mock_session.return_value,
            [
                (COMPANIES_ROUTE, _response(_page([{"id": "c-1", "name": "cronus"}]))),
                ("$skiptoken=abc", _response(_page([{"id": "item-2"}]))),
                ("companies(c-1)/items", _response(_page([{"id": "item-1"}], next_link=next_link))),
            ],
        )

        rows = _rows(_source("items", _make_manager()))

        assert [row["id"] for row in rows] == ["item-1", "item-2"]
        # The second page is fetched from the opaque nextLink; a page without one ends the walk.
        assert urls[-1] == next_link
        assert len(urls) == 3

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_incremental_filter_is_sent_on_the_child_requests(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        _wire_token(mock_auth_session)
        urls = _wire(
            mock_session.return_value,
            [
                (COMPANIES_ROUTE, _response(_page([{"id": "c-1", "name": "cronus"}]))),
                ("companies(c-1)/salesInvoices", _response(_page([{"id": "inv-1"}]))),
            ],
        )

        _rows(
            _source(
                "salesInvoices",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
                incremental_field="lastModifiedDateTime",
            )
        )

        child_query = _query(urls[-1])
        assert unquote_plus(child_query["$filter"][0]) == "lastModifiedDateTime gt 2026-06-01T00:00:00Z"
        # The company enumeration must not be windowed — a company row has no lastModifiedDateTime.
        assert "$filter" not in _query(urls[0])

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_missing_entity_in_one_company_is_skipped(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        _wire_token(mock_auth_session)
        _wire(
            mock_session.return_value,
            [
                (
                    COMPANIES_ROUTE,
                    _response(_page([{"id": "c-1", "name": "cronus"}, {"id": "c-2", "name": "acme"}])),
                ),
                # c-1 doesn't have the extension backing this entity.
                ("companies(c-1)/employees", _response({"error": {"code": "NotFound"}}, status_code=404)),
                ("companies(c-2)/employees", _response(_page([{"id": "emp-1"}]))),
            ],
        )

        rows = _rows(_source("employees", _make_manager()))

        assert [row["id"] for row in rows] == ["emp-1"]

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_permission_error_fails_the_sync(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        _wire_token(mock_auth_session)
        _wire(
            mock_session.return_value,
            [
                (COMPANIES_ROUTE, _response(_page([{"id": "c-1", "name": "cronus"}]))),
                ("companies(c-1)/vendors", _response({"error": {"code": "Forbidden"}}, status_code=403)),
            ],
        )

        with pytest.raises(requests.HTTPError):
            _rows(_source("vendors", _make_manager()))

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_next_link_pointing_off_host_is_rejected(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        _wire_token(mock_auth_session)
        _wire(
            mock_session.return_value,
            [
                (
                    COMPANIES_ROUTE,
                    _response(_page([{"id": "c-1", "name": "cronus"}], next_link="https://evil.example/steal")),
                ),
            ],
        )

        # A tampered nextLink must not carry the bearer token to another host.
        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("companies", _make_manager()))

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_resume_skips_companies_already_completed(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        _wire_token(mock_auth_session)
        urls = _wire(
            mock_session.return_value,
            [
                (
                    COMPANIES_ROUTE,
                    _response(_page([{"id": "c-1", "name": "cronus"}, {"id": "c-2", "name": "acme"}])),
                ),
                ("companies(c-2)/customers", _response(_page([{"id": "cust-2"}]))),
            ],
        )

        manager = _make_manager(
            Dynamics365BusinessCentralResumeConfig(
                paginator_state={"completed": ["companies(c-1)/customers"], "current": None, "child_state": None}
            )
        )
        rows = _rows(_source("customers", manager))

        assert [row["id"] for row in rows] == ["cust-2"]
        assert len(urls) == 2
        assert "companies(c-1)" not in urls[1]

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_resume_restarts_the_company_that_was_mid_page(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        _wire_token(mock_auth_session)
        saved_next = f"{API_ROOT}/companies(c-1)/items?$skiptoken=page-2"
        urls = _wire(
            mock_session.return_value,
            [
                (COMPANIES_ROUTE, _response(_page([{"id": "c-1", "name": "cronus"}]))),
                ("$skiptoken=page-2", _response(_page([{"id": "item-2"}]))),
            ],
        )

        manager = _make_manager(
            Dynamics365BusinessCentralResumeConfig(
                paginator_state={
                    "completed": [],
                    "current": "companies(c-1)/items",
                    "child_state": {"next_url": saved_next},
                }
            )
        )
        rows = _rows(_source("items", manager))

        assert [row["id"] for row in rows] == ["item-2"]
        # The saved link is used instead of the first page of c-1's items.
        assert urls[-1] == saved_next

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_resume_state_from_the_other_endpoint_shape_starts_over(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock
    ) -> None:
        _wire_token(mock_auth_session)
        urls = _wire(
            mock_session.return_value,
            [(COMPANIES_ROUTE, _response(_page([{"id": "c-1", "name": "cronus"}])))],
        )

        # `companies` stores `{"next_url": ...}` while fan-out endpoints store `{"completed": ...}`.
        # Seeding the wrong shape must restart cleanly rather than raise.
        manager = _make_manager(
            Dynamics365BusinessCentralResumeConfig(paginator_state={"completed": [], "current": None})
        )
        rows = _rows(_source("companies", manager))

        assert [row["id"] for row in rows] == ["c-1"]
        assert urls[0].startswith(f"{API_ROOT}/companies")


class TestSourceResponseMetadata:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_metadata_per_endpoint(
        self, mock_session: mock.MagicMock, mock_auth_session: mock.MagicMock, endpoint: str
    ) -> None:
        _wire_token(mock_auth_session)
        _wire(mock_session.return_value, [])
        endpoint_config = BUSINESS_CENTRAL_ENDPOINTS[endpoint]

        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == list(endpoint_config.primary_keys)
        # Business Central doesn't document its page ordering, so an incremental endpoint must only
        # persist its watermark at successful job end — which "desc" guarantees.
        assert response.sort_mode == ("desc" if endpoint_config.cursor_field else "asc")
        if endpoint_config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [endpoint_config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint_config", list(BUSINESS_CENTRAL_ENDPOINTS.values()))
    def test_company_scoped_primary_keys_carry_the_company(self, endpoint_config: BusinessCentralEndpoint) -> None:
        # Business Central ids are only unique within a company, so a fan-out child whose key omits
        # the company would collide across companies and seed duplicate rows in the Delta table.
        if endpoint_config.company_scoped:
            assert endpoint_config.primary_keys[0] == "company_id"
            assert len(endpoint_config.primary_keys) >= 2
        else:
            assert endpoint_config.primary_keys == ("id",)

    @pytest.mark.parametrize("endpoint_config", list(BUSINESS_CENTRAL_ENDPOINTS.values()))
    def test_partition_keys_are_never_the_mutable_cursor(self, endpoint_config: BusinessCentralEndpoint) -> None:
        # Partitioning on lastModifiedDateTime would rewrite partitions on every edit.
        assert endpoint_config.partition_key != "lastModifiedDateTime"
