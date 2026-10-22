from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.cloudflare import (
    DNS_ANALYTICS_ALL_ZONES_FAILED,
    PAGE_SIZE,
    TokenCheck,
    _redact_access_app,
    _redact_custom_hostname,
    _redact_healthcheck,
    _redact_logpush_destination,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.settings import (
    ACCOUNTS_PARENT,
    CLOUDFLARE_ENDPOINTS,
    ENDPOINTS,
    SINGLE_PAGE,
    ZONES_PARENT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.source import CloudflareSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudflare import (
    CloudflareSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(CloudflareSource(), CloudflareSourceConfig(api_token="token"))


def _response(
    result: list[dict[str, Any]],
    total_pages: int | None = None,
) -> ScriptedResponse:
    body: dict[str, Any] = {"success": True, "result": result}
    if total_pages is not None:
        body["result_info"] = {"total_pages": total_pages}
    return ScriptedResponse(json=body)


def _raw_response(body: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json=body)


def _error_response(status_code: int) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json={"success": False, "errors": [{"code": status_code}]})


def _rejected_response(status_code: int, message: str | None = None, code: int = 1000) -> ScriptedResponse:
    error: dict[str, Any] = {"code": code}
    if message is not None:
        error["message"] = message
    return ScriptedResponse(status=status_code, json={"success": False, "errors": [error]})


class TestValidateCredentials:
    def test_valid_on_verify_success(self) -> None:
        with scripted_network([_response([], total_pages=1)]) as network:
            assert validate_credentials("token") == TokenCheck(is_valid=True, status=200)
        assert network.requests_log[0].path == "/client/v4/user/tokens/verify"
        assert network.requests_log[0].headers["authorization"] == "Bearer token"

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_invalid_on_error_status(self, status_code: int) -> None:
        # The status flows back so the caller can tell a rejected token from a 5xx/unreachable one.
        with scripted_network(always(_error_response(status_code))):
            check = validate_credentials("token")
        assert (check.is_valid, check.status) == (False, status_code)

    def test_transient_status_skips_the_fallback_probe(self) -> None:
        with scripted_network(always(_error_response(500))) as network:
            assert validate_credentials("token") == TokenCheck(is_valid=False, status=500)
        # A 5xx says nothing about the token, so probing twice more only delays the retry advice.
        assert {request.path for request in network.requests_log} == {"/client/v4/user/tokens/verify"}

    def test_valid_when_verify_refuses_but_a_parent_list_reads(self) -> None:
        # An account-owned token can't be verified at /user/tokens/verify but can still sync.
        with scripted_network([_rejected_response(400, "Invalid API Token"), _response([{"id": "z1"}], 1)]) as network:
            assert validate_credentials("token") == TokenCheck(is_valid=True, status=200)
        assert [request.path for request in network.requests_log] == [
            "/client/v4/user/tokens/verify",
            "/client/v4/zones",
        ]

    def test_falls_through_to_the_second_parent_list(self) -> None:
        with scripted_network(
            [_rejected_response(400, "Invalid API Token"), _error_response(403), _response([{"id": "a1"}], 1)]
        ) as network:
            assert validate_credentials("token") == TokenCheck(is_valid=True, status=200)
        assert [request.path for request in network.requests_log] == [
            "/client/v4/user/tokens/verify",
            "/client/v4/zones",
            "/client/v4/accounts",
        ]

    def test_probe_exception_leaves_the_question_open(self) -> None:
        # Verify's refusal decides nothing on its own, so two probes that never got an answer
        # leave the token unjudged. Reporting it rejected would send someone off to rebuild a
        # token that was fine.
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/user/tokens/verify"):
                return _rejected_response(400, "Invalid API Token")
            raise ConnectionResetError("boom")

        with scripted_network(respond):
            check = validate_credentials("token")
        assert check == TokenCheck(is_valid=False, status=None)
        assert check.is_transient

    def test_definitive_probe_failures_are_not_transient(self) -> None:
        with scripted_network(
            [_rejected_response(400, "Invalid API Token"), _error_response(403), _error_response(403)]
        ):
            check = validate_credentials("token")
        assert check.is_transient is False
        assert check.is_malformed is False

    def test_unparseable_authorization_header_is_malformed(self) -> None:
        with scripted_network([_rejected_response(400, "Invalid request headers", code=6003)]) as network:
            assert validate_credentials("token").is_malformed is True
        # The probes send the same header, so a transient probe must not hide the malformed verdict.
        assert len(network.requests_log) == 1


class TestPagination:
    def test_full_page_without_result_info_continues(self) -> None:
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        result = _driver().run("accounts", [_response(full_page), _response([{"id": "tail"}])])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("page") == ["1", "2"]


class TestZoneFanout:
    def test_dns_records_fan_out_over_zones_and_inject_zone_id(self) -> None:
        result = _driver().run(
            "dns_records",
            [
                _response([{"id": "z1"}, {"id": "z2"}], total_pages=1),
                _response([{"id": "r1"}], total_pages=1),
                _response([{"id": "r2"}], total_pages=1),
            ],
        )

        assert result.raised is None
        assert [(r["id"], r["_zone_id"]) for r in result.rows] == [("r1", "z1"), ("r2", "z2")]
        assert result.paths == [
            "/client/v4/zones",
            "/client/v4/zones/z1/dns_records",
            "/client/v4/zones/z2/dns_records",
        ]

    def test_dns_records_reraises_unexpected_zone_error(self) -> None:
        result = _driver().run(
            "dns_records",
            [
                _response([{"id": "z1"}], total_pages=1),
                _error_response(400),
            ],
        )

        assert isinstance(result.raised, requests.HTTPError)

    def test_forbidden_zone_listing_propagates(self) -> None:
        # No zone access at all (the top-level listing) must still fail loudly
        # so the schema is flagged non-retryable rather than silently emptied.
        result = _driver().run("dns_records", [_error_response(403)])

        assert isinstance(result.raised, requests.HTTPError)


class TestRetry:
    def test_429_honors_retry_after_and_exhausts_attempts(self) -> None:
        # Retry-After of 0 keeps the test fast while still exercising the honored-wait path.
        result = _driver().run(
            "zones",
            always(
                ScriptedResponse(
                    status=429,
                    json={"success": False, "errors": [{"code": 429}]},
                    headers={"Retry-After": "0"},
                )
            ),
        )

        assert isinstance(result.raised, RESTClientRetryableError)
        assert result.raised.retry_after == 0.0
        # Exhausts all attempts since every page stays rate-limited.
        assert len(result.requests) == 5


class TestCloudflareSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = CLOUDFLARE_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_response([], total_pages=1)])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == list(config.primary_keys)
        assert response.sort_mode is None
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestEndpointConfigConsistency:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_path_placeholder_matches_declared_parent(self, endpoint) -> None:
        # A path templated on one parent but fanned out from the other raises KeyError
        # mid-sync, which only shows up once a customer syncs that table.
        config = CLOUDFLARE_ENDPOINTS[endpoint]
        assert ("{zone_id}" in config.path) is (config.parent == ZONES_PARENT)
        assert ("{account_id}" in config.path) is (config.parent == ACCOUNTS_PARENT)
        if config.parent is not None:
            assert config.parent_key is not None


class TestAccountFanout:
    @pytest.mark.parametrize("status_code", [403, 404])
    def test_skips_account_the_token_cannot_read(self, status_code: int) -> None:
        result = _driver().run(
            "kv_namespaces",
            [
                _response([{"id": "a1"}, {"id": "a2"}], total_pages=1),
                _error_response(status_code),
                _response([{"id": "n2"}], total_pages=1),
            ],
        )

        assert result.raised is None
        assert [(r["id"], r["_account_id"]) for r in result.rows] == [("n2", "a2")]


class TestSinglePageEndpoints:
    @pytest.mark.parametrize(
        "endpoint",
        [name for name, config in CLOUDFLARE_ENDPOINTS.items() if config.pagination == SINGLE_PAGE],
    )
    def test_never_requests_a_second_page(self, endpoint: str) -> None:
        # These endpoints document no page params, so Cloudflare ignores `page` and would
        # return the same rows forever if the page-number paginator were used.
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        result = _driver().run(endpoint, [_response([{"id": "z1"}], total_pages=1), _response(full_page)])

        assert result.raised is None
        assert len(result.requests) == 2
        assert result.requests[1].param("page") is None
        assert result.requests[1].param("per_page") is None


def _dns_groups(*groups: tuple[str, str, int, int]) -> ScriptedResponse:
    return _raw_response(
        {
            "data": {
                "viewer": {
                    "zones": [
                        {
                            "dnsAnalyticsAdaptiveGroups": [
                                {
                                    "count": count,
                                    "dimensions": {
                                        "queryType": query_type,
                                        "responseCode": response_code,
                                        "responseCached": cached,
                                    },
                                }
                                for query_type, response_code, cached, count in groups
                            ]
                        }
                    ]
                }
            },
            "errors": None,
        }
    )


def _graphql_error(message: str) -> ScriptedResponse:
    return _raw_response({"data": None, "errors": [{"message": message}]})


class TestDnsAnalyticsReport:
    def test_cached_groups_sum_into_report_columns_and_unreadable_zones_are_skipped(self) -> None:
        result = _driver().run(
            "dns_analytics_report",
            [
                _response([{"id": "z1"}, {"id": "z2"}], total_pages=1),
                _graphql_error("not authorized for zone z1"),
                _dns_groups(("A", "NOERROR", 1, 6), ("A", "NOERROR", 0, 4), ("MX", "NXDOMAIN", 0, 2)),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"queryType": "A", "responseCode": "NOERROR", "queryCount": 10, "uncachedCount": 4, "_zone_id": "z2"},
            {"queryType": "MX", "responseCode": "NXDOMAIN", "queryCount": 2, "uncachedCount": 2, "_zone_id": "z2"},
        ]
        graphql_request = result.requests[2]
        assert (graphql_request.method, graphql_request.path) == ("POST", "/client/v4/graphql")
        assert graphql_request.json()["variables"]["zoneTag"] == "z2"

    def test_fails_when_every_zone_is_refused(self) -> None:
        result = _driver().run(
            "dns_analytics_report",
            [
                _response([{"id": "z1"}, {"id": "z2"}], total_pages=1),
                _graphql_error("unknown field dnsAnalyticsAdaptiveGroups"),
                _graphql_error("unknown field dnsAnalyticsAdaptiveGroups"),
            ],
        )

        assert isinstance(result.raised, ValueError)
        assert DNS_ANALYTICS_ALL_ZONES_FAILED in str(result.raised)
        assert "unknown field dnsAnalyticsAdaptiveGroups" in str(result.raised)


class TestLogpushDestinationRedaction:
    @pytest.mark.parametrize(
        "conf,expected",
        [
            (
                "s3://bucket/logs?region=us-east-1&access-key-id=AKIA&secret-access-key=shh",
                "s3://bucket/logs?region=us-east-1&access-key-id=REDACTED&secret-access-key=REDACTED",
            ),
            (
                "https://logs.example.com?header_Authorization=Bearer+tok&ddsource=cloudflare",
                "https://logs.example.com?header_Authorization=REDACTED&ddsource=cloudflare",
            ),
            # No secret-bearing param — left byte-for-byte unchanged.
            ("s3://bucket/logs?region=us-east-1", "s3://bucket/logs?region=us-east-1"),
            ("gs://bucket/logs", "gs://bucket/logs"),
        ],
    )
    def test_redacts_only_secret_query_params(self, conf, expected) -> None:
        assert _redact_logpush_destination({"destination_conf": conf}) == {"destination_conf": expected}

    def test_leaves_non_string_conf_untouched(self) -> None:
        row = {"destination_conf": None, "id": "j1"}
        assert _redact_logpush_destination(row) == row

    def test_secret_is_stripped_when_synced(self) -> None:
        # Guards that the redaction data_map is actually wired to the logpush_jobs resource.
        result = _driver().run(
            "logpush_jobs",
            [
                _response([{"id": "z1"}], total_pages=1),
                _response([{"id": "j1", "destination_conf": "s3://b/logs?secret-access-key=SUPERSECRET"}]),
            ],
        )

        assert result.raised is None
        assert "SUPERSECRET" not in result.rows[0]["destination_conf"]
        assert result.rows[0]["destination_conf"] == "s3://b/logs?secret-access-key=REDACTED"


class TestAccessAppRedaction:
    def test_redacts_scim_authentication_but_keeps_scheme(self) -> None:
        row = {
            "id": "app1",
            "scim_config": {"enabled": True, "authentication": {"scheme": "oauthbearertoken", "token": "shh"}},
        }

        result = _redact_access_app(row)

        assert result["scim_config"] == {
            "enabled": True,
            "authentication": {"scheme": "oauthbearertoken", "token": "REDACTED"},
        }

    def test_redacts_each_authentication_in_a_list(self) -> None:
        row = {"scim_config": {"authentication": [{"scheme": "httpbasic", "user": "u", "password": "p"}]}}

        result = _redact_access_app(row)

        assert result["scim_config"]["authentication"] == [
            {"scheme": "httpbasic", "user": "REDACTED", "password": "REDACTED"}
        ]

    def test_redacts_saas_app_client_secret_only(self) -> None:
        row = {"saas_app": {"auth_type": "oidc", "client_id": "cid", "client_secret": "shh"}}

        result = _redact_access_app(row)

        assert result["saas_app"] == {"auth_type": "oidc", "client_id": "cid", "client_secret": "REDACTED"}

    def test_leaves_rows_without_secret_blocks_untouched(self) -> None:
        row = {"id": "app1", "name": "My app"}
        assert _redact_access_app(row) == row

    def test_secrets_are_stripped_when_synced(self) -> None:
        # Guards that the redaction data_map is actually wired to the access_apps resource.
        result = _driver().run(
            "access_apps",
            [
                _response([{"id": "a1"}], total_pages=1),
                _response(
                    [
                        {
                            "id": "app1",
                            "scim_config": {"authentication": {"scheme": "oauthbearertoken", "token": "SUPERSECRET"}},
                        }
                    ],
                    total_pages=1,
                ),
            ],
        )

        assert result.raised is None
        assert result.rows[0]["scim_config"]["authentication"] == {
            "scheme": "oauthbearertoken",
            "token": "REDACTED",
        }


class TestHealthcheckRedaction:
    def test_redacts_http_config_header_values_keeping_names(self) -> None:
        row = {
            "id": "hc1",
            "http_config": {"method": "GET", "header": {"Host": ["example.com"], "Authorization": ["Bearer tok"]}},
        }

        result = _redact_healthcheck(row)

        assert result["http_config"] == {
            "method": "GET",
            "header": {"Host": ["REDACTED"], "Authorization": ["REDACTED"]},
        }

    def test_leaves_rows_without_http_headers_untouched(self) -> None:
        row = {"id": "hc1", "http_config": {"method": "GET"}}
        assert _redact_healthcheck(row) == row

    def test_auth_header_is_stripped_when_synced(self) -> None:
        # Guards that the redaction data_map is actually wired to the healthchecks resource.
        result = _driver().run(
            "healthchecks",
            [
                _response([{"id": "z1"}], total_pages=1),
                _response(
                    [{"id": "hc1", "http_config": {"header": {"Authorization": ["Bearer SUPERSECRET"]}}}], total_pages=1
                ),
            ],
        )

        assert result.raised is None
        assert result.rows[0]["http_config"]["header"] == {"Authorization": ["REDACTED"]}


class TestCustomHostnameRedaction:
    def test_drops_ssl_custom_key_keeping_other_metadata(self) -> None:
        row = {
            "id": "h1",
            "ssl": {"status": "active", "custom_certificate": "-----CERT-----", "custom_key": "-----PRIVATE KEY-----"},
        }

        result = _redact_custom_hostname(row)

        assert result["ssl"] == {"status": "active", "custom_certificate": "-----CERT-----"}

    def test_private_key_is_dropped_when_synced(self) -> None:
        # Guards that the redaction data_map is actually wired to the custom_hostnames resource.
        result = _driver().run(
            "custom_hostnames",
            [
                _response([{"id": "z1"}], total_pages=1),
                _response([{"id": "h1", "ssl": {"status": "active", "custom_key": "SUPERSECRET"}}], total_pages=1),
            ],
        )

        assert result.raised is None
        assert "custom_key" not in result.rows[0]["ssl"]


class TestAuditLogsIncremental:
    @pytest.mark.parametrize(
        "last_value, expected_since",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_filters_server_side_from_the_watermark(self, last_value: Any, expected_since: str) -> None:
        result = _driver().run(
            "audit_logs",
            [_response([{"id": "a1"}], total_pages=1), _response([{"id": "l1"}], total_pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.requests[1].param("since") == expected_since
