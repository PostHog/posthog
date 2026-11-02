from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.simplesat import (
    SimplesatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.settings import (
    ENDPOINTS,
    SIMPLESAT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.simplesat import (
    SIMPLESAT_BASE_URL,
    SimplesatResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.source import SimplesatSource


def _response(
    list_key: str,
    items: Any,
    *,
    next_url: Optional[str] = None,
    include_key: bool = True,
    status: int = 200,
) -> ScriptedResponse:
    body: dict[str, Any] = {"count": 0, "next": next_url, "previous": None}
    if include_key:
        body[list_key] = items
    return ScriptedResponse(status=status, json=body)


def _driver() -> SourceDriver:
    return SourceDriver(SimplesatSource(), SimplesatSourceConfig(api_key="ss-key"))


class TestPagination:
    def test_resumes_from_saved_cursor_without_refetching_first_page(self) -> None:
        next_url = f"{SIMPLESAT_BASE_URL}/surveys?page=2&page_size=100"

        result = _driver().run(
            "surveys",
            [_response("surveys", [{"id": 5}], next_url=None)],
            resume_state=SimplesatResumeConfig(next_url=next_url),
        )

        assert result.rows == [{"id": 5}]
        # The one and only request goes straight to the saved cursor — the first page is never fetched.
        assert result.urls == [next_url]


class TestCustomersRequestShaping:
    @parameterized.expand(
        [
            ("full_refresh", None, None, {}),
            ("first_incremental_run_has_no_filter", "modified", None, {}),
            (
                "modified_aware_datetime",
                "modified",
                datetime(2026, 3, 1, 12, 30, 45, 123456, tzinfo=UTC),
                {"modified_after": "2026-03-01T12:30:45.123456Z"},
            ),
            (
                "modified_naive_datetime_is_utc",
                "modified",
                datetime(2026, 3, 1, 12, 30, 45),
                {"modified_after": "2026-03-01T12:30:45Z"},
            ),
            ("created_date", "created", date(2026, 3, 1), {"created_after": "2026-03-01T00:00:00Z"}),
            ("created_string", "created", "2026-03-01T00:00:00Z", {"created_after": "2026-03-01T00:00:00Z"}),
        ]
    )
    def test_incremental_filter_params(
        self,
        _name: str,
        incremental_field: Optional[str],
        last_value: Any,
        expected_filter: dict[str, str],
    ) -> None:
        page_2 = f"{SIMPLESAT_BASE_URL}/customers?page=2&page_size=250"
        result = _driver().run(
            "customers",
            [
                _response("customers", [{"id": 1}], next_url=page_2),
                _response("customers", [{"id": 2}], next_url=None),
            ],
            incremental_field=incremental_field,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}]
        first_query = parse_qs(urlparse(result.urls[0]).query)
        assert first_query == {"page_size": ["250"], **{k: [v] for k, v in expected_filter.items()}}
        # Later pages follow the `next` URL verbatim.
        assert result.urls[1] == page_2

    @parameterized.expand([(e,) for e in ENDPOINTS if e != "customers"])
    def test_full_refresh_endpoints_ignore_incremental_inputs(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            always(_response(endpoint, [])),
            incremental_field="modified",
            db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
        )

        assert parse_qs(urlparse(result.urls[0]).query) == {"page_size": ["100"]}


class TestHostPinning:
    def test_off_origin_next_url_is_rejected_before_it_is_fetched(self) -> None:
        evil = "https://evil.example.com/api/v1/surveys?page=2"

        result = _driver().run("surveys", [_response("surveys", [{"id": 1}], next_url=evil)])

        # A pagination cursor pointing off the Simplesat host must not be followed — it would leak the
        # customer's API key to another origin.
        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        # Only the first (on-host) page was actually sent; the off-host URL never left the process.
        assert len(result.requests) == 1

    def test_off_origin_resume_url_is_rejected(self) -> None:
        evil = "https://evil.example.com/api/v1/surveys?page=2"

        result = _driver().run(
            "surveys",
            [_response("surveys", [{"id": 5}], next_url=None)],
            resume_state=SimplesatResumeConfig(next_url=evil),
        )

        # A tampered saved cursor is rejected before any request is made.
        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert result.requests == []

    def test_redirect_is_rejected(self) -> None:
        redirect = ScriptedResponse(status=302, headers={"Location": "https://evil.example.com/steal"})

        result = _driver().run("surveys", [redirect])

        # Redirects are disabled, so a 3xx can't smuggle the request (and API key) to another origin.
        assert isinstance(result.raised, ValueError)
        assert "edirect" in str(result.raised)
        assert result.urls == [f"{SIMPLESAT_BASE_URL}/surveys?page_size=100"]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_retry_then_reraise(self, _name: str, status: int) -> None:
        result = _driver().run("surveys", always(_response("surveys", [], status=status)))

        assert isinstance(result.raised, RESTClientRetryableError)
        # Retried up to the client's attempt cap before giving up.
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_immediately(self, _name: str, status: int) -> None:
        result = _driver().run("surveys", [_response("surveys", [], status=status)])

        assert isinstance(result.raised, requests.HTTPError)
        # A 4xx is permanent — no retry.
        assert len(result.requests) == 1

    def test_non_dict_body_is_retried(self) -> None:
        result = _driver().run("surveys", always(ScriptedResponse(json=[{"id": 1}])))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    def test_non_list_resource_key_is_retried(self) -> None:
        result = _driver().run("surveys", always(_response("surveys", {"nope": 1}, next_url=None)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    def test_missing_resource_key_is_retried(self) -> None:
        # A response envelope without the resource key must not silently sync zero rows.
        result = _driver().run("surveys", always(_response("surveys", None, include_key=False, next_url=None)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5


class TestValidateCredentials:
    def test_probe_disables_redirects_to_protect_api_key(self) -> None:
        # The X-Simplesat-Token header rides on the probe; the session must be built with redirects
        # pinned off so a redirect can't replay the key to the redirect target during validation.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("ss-key")

        assert network.session_options[0]["allow_redirects"] is False
        assert network.requests_log[0].headers["x-simplesat-token"] == "ss-key"


class TestSimplesatSourceResponse:
    @parameterized.expand([(e, ["created"] if e == "customers" else None) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str, expected_partition_keys: Optional[list[str]]) -> None:
        response = _driver().run(endpoint, always(_response(endpoint, []))).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Only customers documents a stable creation timestamp to partition on.
        assert response.partition_keys == expected_partition_keys
        assert response.partition_mode == ("datetime" if expected_partition_keys else None)

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SIMPLESAT_ENDPOINTS.values())
        assert set(SIMPLESAT_ENDPOINTS) == set(ENDPOINTS)

    def test_list_key_matches_endpoint_name(self) -> None:
        assert all(config.list_key == config.name for config in SIMPLESAT_ENDPOINTS.values())
