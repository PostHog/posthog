from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus import emailoctopus
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.emailoctopus import (
    EMAILOCTOPUS_BASE_URL as BASE,
    EmailOctopusResumeConfig,
    _base_url_for_version,
    _build_child_params,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.settings import (
    CAMPAIGN_REPORT_STATUSES,
    EMAILOCTOPUS_ENDPOINTS,
    EmailOctopusFanOut,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.source import EmailOctopusSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.emailoctopus import (
    EmailOctopusSourceConfig,
)


def _fanout(endpoint: str) -> EmailOctopusFanOut:
    fanout = EMAILOCTOPUS_ENDPOINTS[endpoint].fanout
    assert fanout is not None
    return fanout


CONTACTS_FANOUT = _fanout("contacts")


def _driver() -> SourceDriver:
    return SourceDriver(EmailOctopusSource(), EmailOctopusSourceConfig(api_key="eo_key"))


def _page(rows: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": rows, "paging": {"next": {"url": next_url} if next_url else None}})


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("microseconds_dropped", datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45Z"),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2024-01-19T12:14:28Z", "2024-01-19T12:14:28Z"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestBuildChildParams:
    @parameterized.expand(
        [
            ("last_updated", "last_updated_at", "last_updated_at.gte"),
            ("created", "created_at", "created_at.gte"),
        ]
    )
    def test_server_side_filter(self, _name: str, field: str, expected_param: str) -> None:
        params = _build_child_params(
            CONTACTS_FANOUT, "subscribed", incremental_field=field, filter_value="2026-01-01T00:00:00Z"
        )
        assert params[expected_param] == "2026-01-01T00:00:00Z"
        assert params["status"] == "subscribed"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("eo_key") is expected
        assert [request.path for request in network.requests_log] == ["/lists"]
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer eo_key"

    def test_tracked_session_redacts_api_key(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("eo_secret")
        # The key must be passed as a redaction value so it can't leak into tracked HTTP logs.
        assert network.session_options == [{"redact_values": ("eo_secret",)}]


class TestApiVersionDispatch:
    # EmailOctopus serves every version from the one REST host, so both supported labels — and any
    # undeclared pin honored verbatim by resolve_api_version — must resolve to it.
    @parameterized.expand([("v1",), ("v2",), ("some-undeclared-label",)])
    def test_base_url_resolves_to_rest_host(self, api_version: str) -> None:
        assert _base_url_for_version(api_version) == BASE

    @parameterized.expand([("v1",), ("v2",)])
    def test_threads_version_into_request_host(self, api_version: str) -> None:
        # Route each version to a distinct sentinel host so the assertion fails if the version stops
        # being threaded into the base-URL selection (e.g. reverts to a hardcoded host).
        sentinel = f"https://host-{api_version}.test"
        with mock.patch.object(emailoctopus, "_base_url_for_version", lambda version: f"https://host-{version}.test"):
            result = _driver().run("lists", [_page([{"id": "L1"}])], api_version=api_version)
        assert result.raised is None
        assert result.urls
        assert all(url.startswith(sentinel) for url in result.urls)


class TestHostPinning:
    @parameterized.expand(
        [("top_level", "lists", f"{BASE}/lists"), ("fan_out_child", "list_tags", f"{BASE}/lists/L1/tags")]
    )
    def test_off_host_next_url_is_refused_before_the_request_goes_out(
        self, _name: str, endpoint: str, paged_url: str
    ) -> None:
        # Every request carries the customer's API key as a bearer header, and this source follows
        # `paging.next.url` verbatim. A spoofed next URL must be refused before the credential
        # leaves the process.
        evil_url = "https://evil.example.com/lists?starting_after=cur1"
        script = (
            [_page([{"id": "L1"}], evil_url)]
            if endpoint == "lists"
            else [_page([{"id": "L1"}]), _page([{"tag": "vip"}], evil_url)]
        )
        result = _driver().run(endpoint, script)
        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert result.paths == (["/lists"] if endpoint == "lists" else ["/lists", "/lists/L1/tags"])
        assert result.requests[-1].url.startswith(paged_url)
        assert all(request.headers["authorization"] == "Bearer eo_key" for request in result.requests)

    def test_off_host_resume_url_is_refused(self) -> None:
        # Resume state is read back from Redis, so a poisoned cursor is seeded straight into the
        # paginator. Host pinning covers that seed too.
        evil_url = "https://evil.example.com/campaigns?starting_after=cur5"
        result = _driver().run("campaigns", [], resume_state=EmailOctopusResumeConfig(next_url=evil_url))
        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert result.requests == []


class TestContactsFanOut:
    @staticmethod
    def _one_list_pages(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/lists":
            return _page([{"id": "L1"}])
        assert request.path == "/lists/L1/contacts"
        return _page([])

    def test_applies_server_side_incremental_filter_on_every_status(self) -> None:
        result = _driver().run(
            "contacts",
            self._one_list_pages,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="last_updated_at",
        )
        contact_requests = [request for request in result.requests if "contacts" in request.path]
        assert result.raised is None
        assert contact_requests
        assert {request.param("status") for request in contact_requests} == {"subscribed", "unsubscribed", "pending"}
        assert all(request.param("last_updated_at.gte") == "2026-01-01T00:00:00Z" for request in contact_requests)

    def test_non_404_error_propagates(self) -> None:
        # A non-404 client error is not swallowed by the 404 skip — it fails the sync.
        result = _driver().run("contacts", [_page([{"id": "L1"}]), ScriptedResponse(status=403, json={})])
        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/lists", "/lists/L1/contacts"]
        assert result.requests[-1].param("status") == "subscribed"


class TestCampaignReportsFanOut:
    @staticmethod
    def _pages(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/campaigns":
            return _page([{"id": "C1", "status": "sent"}])
        assert request.path == "/campaigns/C1/reports"
        status = request.param("status")
        rows = [{"contact_id": "ct1", "occurred_at": "2026-01-02T03:04:05+00:00"}] if status == "opened" else []
        return ScriptedResponse(json={"status": status, "data": rows, "paging": {"next": None}})

    def test_attaches_campaign_id_and_the_requested_status(self) -> None:
        # The envelope states the status once and `data_selector` drops it, so without the attach
        # step the eight walks would be indistinguishable in the table.
        result = _driver().run("campaign_reports", self._pages)
        assert result.raised is None
        assert result.rows == [
            {"contact_id": "ct1", "occurred_at": "2026-01-02T03:04:05+00:00", "campaign_id": "C1", "status": "opened"}
        ]
        assert {request.param("status") for request in result.requests if "/reports" in request.path} == set(
            CAMPAIGN_REPORT_STATUSES
        )

    @parameterized.expand([("draft",), ("error",)])
    def test_skips_campaigns_that_never_sent(self, campaign_status: str) -> None:
        # A campaign that never sent has no report. Fanning out over it would spend eight requests
        # per sync on a rejection we could not tell apart from a genuinely malformed one.
        result = _driver().run("campaign_reports", always(_page([{"id": "C1", "status": campaign_status}])))
        assert result.raised is None
        assert result.rows == []
        assert all("/reports" not in path for path in result.paths)


class TestUnpaginatedCampaignFanOuts:
    def test_links_attach_campaign_id_and_stop_after_one_page(self) -> None:
        # The links endpoint takes no pagination params and returns no `paging` block; a next-URL
        # paginator would have nothing to follow, so the walk must terminate on the first response.
        result = _driver().run(
            "campaign_report_links",
            [
                _page([{"id": "C1", "status": "sent"}]),
                ScriptedResponse(
                    json={"data": [{"url": "https://example.com/promo-1", "clicked_total": 10, "clicked_unique": 7}]}
                ),
            ],
        )
        assert result.raised is None
        assert result.rows == [
            {"url": "https://example.com/promo-1", "clicked_total": 10, "clicked_unique": 7, "campaign_id": "C1"}
        ]
        assert result.paths == ["/campaigns", "/campaigns/C1/reports/links"]
        assert result.requests[-1].param("limit") is None


class TestSourceResponse:
    @parameterized.expand(
        [
            ("lists", ["id"], "created_at"),
            ("campaigns", ["id"], "created_at"),
            ("contacts", ["list_id", "id"], "created_at"),
            ("campaign_reports", ["campaign_id", "status", "contact_id"], "occurred_at"),
            ("campaign_report_summaries", ["id"], None),
            ("campaign_report_links", ["campaign_id", "url"], None),
            ("list_tags", ["list_id", "tag"], None),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, expected_pks: list[str], partition_key: str | None
    ) -> None:
        result = _driver().run(endpoint, always(_page([])))
        response = result.response
        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.sort_mode == "asc"
        assert EMAILOCTOPUS_ENDPOINTS[endpoint].partition_key == partition_key
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [partition_key]
