from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.dynamics_365_business_central import (
    BUSINESS_CENTRAL_HOST,
    BusinessCentralConfigurationError,
    Dynamics365BusinessCentralResumeConfig,
    build_base_url,
    build_incremental_params,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.settings import (
    BUSINESS_CENTRAL_ENDPOINTS,
    ENDPOINTS,
    BusinessCentralEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.source import (
    Dynamics365BusinessCentralSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamics365businesscentral import (
    Dynamics365BusinessCentralSourceConfig,
)

TENANT = "contoso.onmicrosoft.com"
ENVIRONMENT = "production"
API_VERSION = "v2.0"
API_ROOT = f"https://{BUSINESS_CENTRAL_HOST}/v2.0/{TENANT}/{ENVIRONMENT}/api/{API_VERSION}"
TOKEN_PATH = f"/{TENANT}/oauth2/v2.0/token"


def _driver() -> SourceDriver:
    return SourceDriver(
        Dynamics365BusinessCentralSource(),
        Dynamics365BusinessCentralSourceConfig(
            tenant_id=TENANT,
            environment=ENVIRONMENT,
            client_id="client-id",
            client_secret="client-secret",
        ),
    )


def _page(rows: list[dict[str, Any]], next_link: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"@odata.context": f"{API_ROOT}/$metadata", "value": rows}
    if next_link:
        payload["@odata.nextLink"] = next_link
    return payload


def _token(token: str = "entra-token") -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": token, "expires_in": 3599, "token_type": "Bearer"})


def _answers(*pages: ScriptedResponse) -> list[ScriptedResponse]:
    return [_token(), *pages]


def _page_response(rows: list[dict[str, Any]], next_link: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json=_page(rows, next_link))


def _token_then_status(status_code: int) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == TOKEN_PATH:
            return _token()
        return ScriptedResponse(status=status_code, json={"value": []})

    return respond


def _requests_without_token(requests_log: list[RecordedRequest]) -> list[RecordedRequest]:
    return [request for request in requests_log if request.path != TOKEN_PATH]


def _resume_state(paginator_state: dict[str, Any]) -> Dynamics365BusinessCentralResumeConfig:
    return Dynamics365BusinessCentralResumeConfig(paginator_state=paginator_state)


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
    def test_status_mapping(
        self,
        status_code: int,
        expected_valid: bool,
    ) -> None:
        with scripted_network(_token_then_status(status_code)) as network:
            valid, message = validate_credentials(TENANT, ENVIRONMENT, "client-id", "client-secret", API_VERSION)

        assert valid is expected_valid
        assert (message is None) is expected_valid
        assert network.requests_log[0].path == TOKEN_PATH
        assert network.requests_log[1].path == f"/v2.0/{TENANT}/{ENVIRONMENT}/api/{API_VERSION}/companies"

    def test_sends_the_minted_bearer_token(self) -> None:
        with scripted_network([_token("minted-token"), ScriptedResponse(json={"value": []})]) as network:
            assert validate_credentials(TENANT, ENVIRONMENT, "client-id", "client-secret", API_VERSION) == (True, None)

        token_request, data_request = network.requests_log
        assert token_request.method == "POST"
        assert token_request.url == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
        token_body = parse_qs(token_request.body.decode() if token_request.body else "")
        assert token_body["grant_type"] == ["client_credentials"]
        assert token_body["scope"] == [f"https://{BUSINESS_CENTRAL_HOST}/.default"]
        assert token_body["client_secret"] == ["client-secret"]
        assert data_request.headers["authorization"] == "Bearer minted-token"

    def test_entra_token_rejection_is_reported_without_the_internal_marker(self) -> None:
        with scripted_network(
            [ScriptedResponse(status=401, json={"error": "invalid_client", "error_description": "AADSTS7000215"})]
        ) as network:
            valid, message = validate_credentials(TENANT, ENVIRONMENT, "client-id", "client-secret", API_VERSION)

        assert valid is False
        assert message is not None
        assert "invalid_client" in message
        assert "oauth2_token_config_error" not in message
        assert [request.path for request in network.requests_log] == [TOKEN_PATH]

    def test_bad_environment_name_fails_before_any_request(self) -> None:
        with scripted_network([]) as network:
            valid, message = validate_credentials(TENANT, "prod/../admin", "client-id", "client-secret", API_VERSION)

        assert valid is False
        assert message is not None and "environment name" in message
        assert network.requests_log == []
        assert network.session_options == []

    def test_transport_failure_is_not_valid(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == TOKEN_PATH:
                return _token()
            raise requests.ConnectionError("boom")

        with scripted_network(respond) as network:
            valid, message = validate_credentials(TENANT, ENVIRONMENT, "client-id", "client-secret", API_VERSION)

        assert valid is False
        assert message is not None and "Could not reach Business Central" in message
        assert {request.path for request in network.requests_log} == {
            TOKEN_PATH,
            f"/v2.0/{TENANT}/{ENVIRONMENT}/api/{API_VERSION}/companies",
        }


class TestGetRows:
    def test_companies_is_top_level_and_strips_odata_annotations(self) -> None:
        result = _driver().run(
            "companies",
            _answers(_page_response([{"id": "c-1", "name": "cronus", "@odata.etag": 'W/"1"'}])),
        )

        assert result.raised is None
        assert result.rows == [{"id": "c-1", "name": "cronus"}]
        data_requests = _requests_without_token(result.requests)
        assert len(data_requests) == 1
        assert data_requests[0].url.startswith(f"{API_ROOT}/companies")

    def test_row_bodies_are_kept_out_of_http_sample_capture(self) -> None:
        # Rows carry ledger, payment, bank-account and tax fields the name-based scrubbers can't
        # recognise, so the sync session must opt out of body capture. Dropping `capture=False`
        # would persist raw financial records to the HTTP sample store.
        result = _driver().run("companies", _answers(_page_response([])))

        assert result.raised is None
        assert result.session_options[0]["capture"] is False
        assert result.session_options[0]["redact_values"] == ("client-secret",)

    def test_company_scoped_endpoint_fans_out_and_stamps_the_company(self) -> None:
        result = _driver().run(
            "customers",
            _answers(
                _page_response([{"id": "c-1", "name": "cronus"}, {"id": "c-2", "name": "acme"}]),
                _page_response([{"id": "cust-1"}]),
                _page_response([{"id": "cust-2"}]),
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "cust-1", "company_id": "c-1", "company_name": "cronus"},
            {"id": "cust-2", "company_id": "c-2", "company_name": "acme"},
        ]
        # Single-hop fan-out stays resumable: per-company progress is checkpointed.
        assert result.saved_states
        assert "completed" in result.saved_states[-1].paginator_state
        assert len(_requests_without_token(result.requests)) == 3

    def test_pagination_follows_odata_next_link_and_terminates(self) -> None:
        next_link = f"{API_ROOT}/companies(c-1)/items?$skiptoken=abc"
        result = _driver().run(
            "items",
            _answers(
                _page_response([{"id": "c-1", "name": "cronus"}]),
                _page_response([{"id": "item-1"}], next_link=next_link),
                _page_response([{"id": "item-2"}]),
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["item-1", "item-2"]
        # The second page is fetched from the opaque nextLink; a page without one ends the walk.
        data_requests = _requests_without_token(result.requests)
        assert data_requests[-1].url == next_link
        assert len(data_requests) == 3

    def test_incremental_filter_is_sent_on_the_child_requests(self) -> None:
        result = _driver().run(
            "salesInvoices",
            _answers(
                _page_response([{"id": "c-1", "name": "cronus"}]),
                _page_response([{"id": "inv-1"}]),
            ),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            incremental_field="lastModifiedDateTime",
        )

        assert result.raised is None
        data_requests = _requests_without_token(result.requests)
        assert data_requests[-1].param("$filter") == "lastModifiedDateTime gt 2026-06-01T00:00:00Z"
        # The company enumeration must not be windowed — a company row has no lastModifiedDateTime.
        assert data_requests[0].param("$filter") is None

    def test_missing_entity_in_one_company_is_skipped(self) -> None:
        result = _driver().run(
            "employees",
            _answers(
                _page_response([{"id": "c-1", "name": "cronus"}, {"id": "c-2", "name": "acme"}]),
                # c-1 doesn't have the extension backing this entity.
                ScriptedResponse(status=404, json={"error": {"code": "NotFound"}}),
                _page_response([{"id": "emp-1"}]),
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["emp-1"]

    def test_permission_error_fails_the_sync(self) -> None:
        result = _driver().run(
            "vendors",
            _answers(
                _page_response([{"id": "c-1", "name": "cronus"}]),
                ScriptedResponse(status=403, json={"error": {"code": "Forbidden"}}),
            ),
        )

        assert isinstance(result.raised, requests.HTTPError)

    def test_next_link_pointing_off_host_is_rejected(self) -> None:
        result = _driver().run(
            "companies",
            _answers(_page_response([{"id": "c-1", "name": "cronus"}], next_link="https://evil.example/steal")),
        )

        # A tampered nextLink must not carry the bearer token to another host.
        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert all(request.origin != "https://evil.example" for request in result.requests)

    def test_resume_skips_companies_already_completed(self) -> None:
        result = _driver().run(
            "customers",
            _answers(
                _page_response([{"id": "c-1", "name": "cronus"}, {"id": "c-2", "name": "acme"}]),
                _page_response([{"id": "cust-2"}]),
            ),
            resume_state=_resume_state(
                {"completed": ["companies(c-1)/customers"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["cust-2"]
        data_requests = _requests_without_token(result.requests)
        assert len(data_requests) == 2
        assert "companies(c-1)" not in data_requests[1].url

    def test_resume_restarts_the_company_that_was_mid_page(self) -> None:
        saved_next = f"{API_ROOT}/companies(c-1)/items?$skiptoken=page-2"
        result = _driver().run(
            "items",
            _answers(_page_response([{"id": "c-1", "name": "cronus"}]), _page_response([{"id": "item-2"}])),
            resume_state=_resume_state(
                {
                    "completed": [],
                    "current": "companies(c-1)/items",
                    "child_state": {"next_url": saved_next},
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["item-2"]
        # The saved link is used instead of the first page of c-1's items.
        assert _requests_without_token(result.requests)[-1].url == saved_next

    def test_resume_state_from_the_other_endpoint_shape_starts_over(self) -> None:
        # `companies` stores `{"next_url": ...}` while fan-out endpoints store `{"completed": ...}`.
        # Seeding the wrong shape must restart cleanly rather than raise.
        result = _driver().run(
            "companies",
            _answers(_page_response([{"id": "c-1", "name": "cronus"}])),
            resume_state=_resume_state({"completed": [], "current": None}),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c-1"]
        assert _requests_without_token(result.requests)[0].url.startswith(f"{API_ROOT}/companies")


class TestSourceResponseMetadata:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_metadata_per_endpoint(self, endpoint: str) -> None:
        endpoint_config = BUSINESS_CENTRAL_ENDPOINTS[endpoint]
        pages = [_page_response([])]
        if endpoint_config.company_scoped:
            pages.append(_page_response([]))

        result = _driver().run(endpoint, _answers(*pages))
        assert result.raised is None
        response = result.response
        assert response is not None

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
