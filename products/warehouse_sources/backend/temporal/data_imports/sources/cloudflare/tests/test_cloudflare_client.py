import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.cloudflare import (
    PAGE_SIZE,
    _redact_access_app,
    _redact_custom_hostname,
    _redact_healthcheck,
    _redact_logpush_destination,
    cloudflare_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.settings import (
    ACCOUNTS_PARENT,
    CLOUDFLARE_ENDPOINTS,
    ENDPOINTS,
    SINGLE_PAGE,
    ZONES_PARENT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the cloudflare module.
CLOUDFLARE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.cloudflare.make_tracked_session"
)


def _response(
    result: list[dict[str, Any]],
    total_pages: int | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    body: dict[str, Any] = {"success": True, "result": result}
    if total_pages is not None:
        body["result_info"] = {"total_pages": total_pages}
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    if headers:
        resp.headers.update(headers)
    return resp


def _raw_response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _error_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.url = "https://api.cloudflare.com/client/v4/probe"
    resp._content = json.dumps({"success": False, "errors": [{"code": status_code}]}).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's url/params AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestValidateCredentials:
    @mock.patch(CLOUDFLARE_SESSION_PATCH)
    def test_valid_on_verify_success(self, mock_session) -> None:
        mock_session.return_value.get.return_value = _response([], total_pages=1)
        assert validate_credentials("token") == (True, 200)

    @mock.patch(CLOUDFLARE_SESSION_PATCH)
    def test_invalid_when_success_false(self, mock_session) -> None:
        resp = Response()
        resp.status_code = 200
        resp._content = json.dumps({"success": False, "result": None}).encode()
        mock_session.return_value.get.return_value = resp
        assert validate_credentials("token") == (False, 200)

    @pytest.mark.parametrize("status_code", [401, 403, 500])
    @mock.patch(CLOUDFLARE_SESSION_PATCH)
    def test_invalid_on_error_status(self, mock_session, status_code) -> None:
        mock_session.return_value.get.return_value = _error_response(status_code)
        # The status flows back so the caller can tell a rejected token from a 5xx/unreachable one.
        assert validate_credentials("token") == (False, status_code)

    @mock.patch(CLOUDFLARE_SESSION_PATCH)
    def test_unreachable_on_exception(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") == (False, None)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_zones_paginate_via_total_pages(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "z1"}], total_pages=2),
                _response([{"id": "z2"}], total_pages=2),
            ],
        )

        rows = _rows(cloudflare_source("token", "zones", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["z1", "z2"]
        assert snapshots[0]["params"]["page"] == 1
        assert snapshots[0]["params"]["per_page"] == PAGE_SIZE
        assert snapshots[1]["params"]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_result_info_falls_back_to_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a1"}])])

        rows = _rows(cloudflare_source("token", "accounts", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["a1"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_without_result_info_continues(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        _wire(session, [_response(full_page), _response([{"id": "tail"}])])

        rows = _rows(cloudflare_source("token", "accounts", team_id=1, job_id="j"))

        assert len(rows) == PAGE_SIZE + 1
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], total_pages=0)])

        assert _rows(cloudflare_source("token", "zones", team_id=1, job_id="j")) == []
        assert session.send.call_count == 1


class TestZoneFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_dns_records_fan_out_over_zones_and_inject_zone_id(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "z1"}, {"id": "z2"}], total_pages=1),
                _response([{"id": "r1"}], total_pages=1),
                _response([{"id": "r2"}], total_pages=1),
            ],
        )

        rows = _rows(cloudflare_source("token", "dns_records", team_id=1, job_id="j"))

        assert [(r["id"], r["_zone_id"]) for r in rows] == [("r1", "z1"), ("r2", "z2")]
        assert snapshots[0]["url"] == "https://api.cloudflare.com/client/v4/zones"
        assert snapshots[1]["url"] == "https://api.cloudflare.com/client/v4/zones/z1/dns_records"
        assert snapshots[2]["url"] == "https://api.cloudflare.com/client/v4/zones/z2/dns_records"

    @pytest.mark.parametrize("status_code", [403, 404])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_dns_records_skips_inaccessible_zone_and_continues(self, MockSession, status_code) -> None:
        # A token can list every zone but lack DNS access on a subset; one
        # forbidden zone must not abort the whole stream.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "z1"}, {"id": "z2"}], total_pages=1),
                _error_response(status_code),
                _response([{"id": "r2"}], total_pages=1),
            ],
        )

        rows = _rows(cloudflare_source("token", "dns_records", team_id=1, job_id="j"))

        assert [(r["id"], r["_zone_id"]) for r in rows] == [("r2", "z2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_dns_records_reraises_unexpected_zone_error(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "z1"}], total_pages=1),
                _error_response(400),
            ],
        )

        with pytest.raises(requests.HTTPError):
            _rows(cloudflare_source("token", "dns_records", team_id=1, job_id="j"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_forbidden_zone_listing_propagates(self, MockSession) -> None:
        # No zone access at all (the top-level listing) must still fail loudly
        # so the schema is flagged non-retryable rather than silently emptied.
        session = MockSession.return_value
        _wire(session, [_error_response(403)])

        with pytest.raises(requests.HTTPError):
            _rows(cloudflare_source("token", "dns_records", team_id=1, job_id="j"))

    @pytest.mark.parametrize(
        ("endpoint", "status_code"),
        [("rate_limits", 410), ("custom_certificates", 400)],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_skips_zone_missing_plan_feature_and_continues(self, MockSession, endpoint, status_code) -> None:
        # Cloudflare returns a non-403/404 error when a zone's plan doesn't include a
        # feature (e.g. legacy rate limiting is 410 Gone, custom certs are 400) rather
        # than an empty list — one such zone must not abort the whole stream.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "z1"}, {"id": "z2"}], total_pages=1),
                _error_response(status_code),
                _response([{"id": "r2"}], total_pages=1),
            ],
        )

        rows = _rows(cloudflare_source("token", endpoint, team_id=1, job_id="j"))

        assert [(r["id"], r["_zone_id"]) for r in rows] == [("r2", "z2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_zone_without_id_is_skipped(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"name": "no-id"}, {"id": "z1"}], total_pages=1),
                _response([{"id": "r1"}], total_pages=1),
            ],
        )

        rows = _rows(cloudflare_source("token", "dns_records", team_id=1, job_id="j"))

        assert [(r["id"], r["_zone_id"]) for r in rows] == [("r1", "z1")]
        assert session.send.call_count == 2


class TestRetry:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_429_honors_retry_after_and_exhausts_attempts(self, MockSession) -> None:
        # Retry-After of 0 keeps the test fast while still exercising the honored-wait path.
        session = MockSession.return_value
        responses = [_error_response(429) for _ in range(5)]
        for resp in responses:
            resp.headers["Retry-After"] = "0"
        _wire(session, responses)

        with pytest.raises(RESTClientRetryableError) as exc_info:
            _rows(cloudflare_source("token", "zones", team_id=1, job_id="j"))

        assert exc_info.value.retry_after == 0.0
        # Exhausts all attempts since every page stays rate-limited.
        assert session.send.call_count == 5


class TestCloudflareSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint) -> None:
        MockSession.return_value.headers = {}
        config = CLOUDFLARE_ENDPOINTS[endpoint]
        response = cloudflare_source("token", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == list(config.primary_keys)
        assert response.sort_mode == "asc"
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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_account_scoped_endpoint_fans_out_over_accounts(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "a1"}, {"id": "a2"}], total_pages=1),
                _response([{"id": "n1"}], total_pages=1),
                _response([{"id": "n2"}], total_pages=1),
            ],
        )

        rows = _rows(cloudflare_source("token", "kv_namespaces", team_id=1, job_id="j"))

        assert [(r["id"], r["_account_id"]) for r in rows] == [("n1", "a1"), ("n2", "a2")]
        assert snapshots[0]["url"] == "https://api.cloudflare.com/client/v4/accounts"
        assert snapshots[1]["url"] == "https://api.cloudflare.com/client/v4/accounts/a1/storage/kv/namespaces"
        assert snapshots[2]["url"] == "https://api.cloudflare.com/client/v4/accounts/a2/storage/kv/namespaces"

    @pytest.mark.parametrize("status_code", [403, 404])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_skips_account_the_token_cannot_read(self, MockSession, status_code) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "a1"}, {"id": "a2"}], total_pages=1),
                _error_response(status_code),
                _response([{"id": "n2"}], total_pages=1),
            ],
        )

        rows = _rows(cloudflare_source("token", "kv_namespaces", team_id=1, job_id="j"))

        assert [(r["id"], r["_account_id"]) for r in rows] == [("n2", "a2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_skips_account_missing_billing_usage_entitlement_and_continues(self, MockSession) -> None:
        # Accounts without billing-usage entitlement get a 400 rather than an empty
        # list — one such account must not abort the whole stream.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "a1"}, {"id": "a2"}], total_pages=1),
                _error_response(400),
                _response([{"ts": 1}], total_pages=1),
            ],
        )

        rows = _rows(cloudflare_source("token", "billing_usage", team_id=1, job_id="j"))

        assert [(r["ts"], r["_account_id"]) for r in rows] == [(1, "a2")]


class TestSinglePageEndpoints:
    @pytest.mark.parametrize(
        "endpoint",
        [name for name, config in CLOUDFLARE_ENDPOINTS.items() if config.pagination == SINGLE_PAGE],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_never_requests_a_second_page(self, MockSession, endpoint) -> None:
        # These endpoints document no page params, so Cloudflare ignores `page` and would
        # return the same rows forever if the page-number paginator were used.
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        snapshots = _wire(session, [_response([{"id": "z1"}], total_pages=1), _response(full_page)])

        _rows(cloudflare_source("token", endpoint, team_id=1, job_id="j"))

        assert session.send.call_count == 2
        assert "page" not in snapshots[1]["params"]
        assert "per_page" not in snapshots[1]["params"]


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rulesets_follow_the_after_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "z1"}], total_pages=1),
                _raw_response(
                    {"success": True, "result": [{"id": "r1"}], "result_info": {"cursors": {"after": "next-page"}}}
                ),
                _raw_response({"success": True, "result": [{"id": "r2"}], "result_info": {"cursors": {}}}),
            ],
        )

        rows = _rows(cloudflare_source("token", "rulesets", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["r1", "r2"]
        assert "cursor" not in snapshots[1]["params"]
        assert snapshots[2]["params"]["cursor"] == "next-page"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_r2_buckets_read_rows_from_the_nested_buckets_key(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "a1"}], total_pages=1),
                _raw_response(
                    {"success": True, "result": {"buckets": [{"name": "b1"}]}, "result_info": {"cursor": "c1"}}
                ),
                _raw_response({"success": True, "result": {"buckets": [{"name": "b2"}]}, "result_info": {}}),
            ],
        )

        rows = _rows(cloudflare_source("token", "r2_buckets", team_id=1, job_id="j"))

        assert [(r["name"], r["_account_id"]) for r in rows] == [("b1", "a1"), ("b2", "a1")]


class TestSecurityCenterInsights:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reads_rows_from_the_nested_issues_key(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "a1"}], total_pages=1),
                _raw_response({"success": True, "result": {"issues": [{"id": "i1"}], "count": 1}}),
            ],
        )

        rows = _rows(cloudflare_source("token", "security_center_insights", team_id=1, job_id="j"))

        assert [(r["id"], r["_account_id"]) for r in rows] == [("i1", "a1")]


class TestDnsAnalyticsReport:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_positional_report_arrays_become_named_columns(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "z1"}], total_pages=1),
                _raw_response(
                    {
                        "success": True,
                        "result": {
                            "rows": 1,
                            "data": [{"dimensions": ["A", "NOERROR"], "metrics": [10, 4]}],
                        },
                    }
                ),
            ],
        )

        rows = _rows(cloudflare_source("token", "dns_analytics_report", team_id=1, job_id="j"))

        assert rows == [
            {
                "queryType": "A",
                "responseCode": "NOERROR",
                "queryCount": 10,
                "uncachedCount": 4,
                "_zone_id": "z1",
            }
        ]
        assert snapshots[1]["params"]["metrics"] == "queryCount,uncachedCount"
        assert snapshots[1]["params"]["dimensions"] == "queryType,responseCode"


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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_secret_is_stripped_when_synced(self, MockSession) -> None:
        # Guards that the redaction data_map is actually wired to the logpush_jobs resource.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "z1"}], total_pages=1),
                _response([{"id": "j1", "destination_conf": "s3://b/logs?secret-access-key=SUPERSECRET"}]),
            ],
        )

        rows = _rows(cloudflare_source("token", "logpush_jobs", team_id=1, job_id="j"))

        assert "SUPERSECRET" not in rows[0]["destination_conf"]
        assert rows[0]["destination_conf"] == "s3://b/logs?secret-access-key=REDACTED"


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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_secrets_are_stripped_when_synced(self, MockSession) -> None:
        # Guards that the redaction data_map is actually wired to the access_apps resource.
        session = MockSession.return_value
        _wire(
            session,
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

        rows = _rows(cloudflare_source("token", "access_apps", team_id=1, job_id="j"))

        assert rows[0]["scim_config"]["authentication"] == {"scheme": "oauthbearertoken", "token": "REDACTED"}


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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_header_is_stripped_when_synced(self, MockSession) -> None:
        # Guards that the redaction data_map is actually wired to the healthchecks resource.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "z1"}], total_pages=1),
                _response(
                    [{"id": "hc1", "http_config": {"header": {"Authorization": ["Bearer SUPERSECRET"]}}}], total_pages=1
                ),
            ],
        )

        rows = _rows(cloudflare_source("token", "healthchecks", team_id=1, job_id="j"))

        assert rows[0]["http_config"]["header"] == {"Authorization": ["REDACTED"]}


class TestCustomHostnameRedaction:
    def test_drops_ssl_custom_key_keeping_other_metadata(self) -> None:
        row = {
            "id": "h1",
            "ssl": {"status": "active", "custom_certificate": "-----CERT-----", "custom_key": "-----PRIVATE KEY-----"},
        }

        result = _redact_custom_hostname(row)

        assert result["ssl"] == {"status": "active", "custom_certificate": "-----CERT-----"}

    def test_leaves_rows_without_a_custom_key_untouched(self) -> None:
        row = {"id": "h1", "ssl": {"status": "active"}}
        assert _redact_custom_hostname(row) == row

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_private_key_is_dropped_when_synced(self, MockSession) -> None:
        # Guards that the redaction data_map is actually wired to the custom_hostnames resource.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "z1"}], total_pages=1),
                _response([{"id": "h1", "ssl": {"status": "active", "custom_key": "SUPERSECRET"}}], total_pages=1),
            ],
        )

        rows = _rows(cloudflare_source("token", "custom_hostnames", team_id=1, job_id="j"))

        assert "custom_key" not in rows[0]["ssl"]


class TestAuditLogsIncremental:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_ascending_direction_and_no_since_on_a_full_refresh(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [_response([{"id": "a1"}], total_pages=1), _response([{"id": "l1"}], total_pages=1)],
        )

        _rows(cloudflare_source("token", "audit_logs", team_id=1, job_id="j"))

        assert snapshots[1]["params"]["direction"] == "asc"
        assert "since" not in snapshots[1]["params"]

    @pytest.mark.parametrize(
        "last_value, expected_since",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_filters_server_side_from_the_watermark(self, MockSession, last_value, expected_since) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [_response([{"id": "a1"}], total_pages=1), _response([{"id": "l1"}], total_pages=1)],
        )

        _rows(
            cloudflare_source(
                "token",
                "audit_logs",
                team_id=1,
                job_id="j",
                should_use_incremental_field=True,
                db_incremental_field_last_value=last_value,
            )
        )

        assert snapshots[1]["params"]["since"] == expected_since
