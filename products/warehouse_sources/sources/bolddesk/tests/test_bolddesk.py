from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.sources.bolddesk._config import BoldDeskSourceConfig
from products.warehouse_sources.sources.bolddesk.bolddesk import (
    BoldDeskResumeConfig,
    InvalidBoldDeskDomainError,
    normalize_subdomain,
)
from products.warehouse_sources.sources.bolddesk.source import BoldDeskSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network

API_KEY = "bd-test-key"


def _driver(domain: str = "acme") -> SourceDriver:
    return SourceDriver(BoldDeskSource(), BoldDeskSourceConfig(domain=domain, api_key=API_KEY))


def _page(rows: list[dict[str, Any]], count: int | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"result": rows, "count": count if count is not None else len(rows)})


def _tickets(start: int, n: int) -> list[dict[str, Any]]:
    return [
        {"ticketId": i, "createdOn": "2026-01-01T00:00:00Z", "lastUpdatedOn": "2026-01-02T00:00:00Z"}
        for i in range(start, start + n)
    ]


class TestPagination:
    def test_walks_pages_until_a_short_page_and_saves_the_next_page_before_it(self) -> None:
        result = _driver("https://Acme.bolddesk.com/").run(
            "tickets",
            [_page(_tickets(1, 100), count=150), _page(_tickets(101, 50), count=150)],
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert len(result.rows) == 150
        assert {request.headers.get("host") for request in result.requests} == {"acme.bolddesk.com"}
        assert result.paths == ["/api/v1/tickets", "/api/v1/tickets"]
        assert result.params("Page") == ["1", "2"]
        assert result.params("PerPage") == ["100", "100"]
        assert result.params("OrderBy") == ["ticketId asc", "ticketId asc"]
        assert {request.headers.get("x-api-key") for request in result.requests} == {API_KEY}
        assert result.committed_states == [BoldDeskResumeConfig(next_page=2)]

    def test_resumes_from_the_saved_page(self) -> None:
        result = _driver().run(
            "contacts",
            [_page([{"userId": 1, "createdOn": "2026-01-01T00:00:00Z"}])],
            resume_state=BoldDeskResumeConfig(next_page=3),
        )

        assert result.raised is None
        assert result.params("Page") == ["3"]

    def test_brands_is_one_request_without_paging_params(self) -> None:
        result = _driver().run("brands", [_page([{"brandId": i} for i in range(100)])])

        assert result.raised is None
        assert len(result.rows) == 100
        assert result.paths == ["/api/v1/brands"]
        assert result.params("Page") == [None]
        assert result.params("PerPage") == [None]


class TestIncrementalRequestShaping:
    @pytest.mark.parametrize(
        ("schema", "incremental_field", "last_value", "expected"),
        [
            (
                "tickets",
                "lastUpdatedOn",
                datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
                {"Q": 'lastmodifiedon:{"from":"2026-01-02T03:04:05.000Z"}'},
            ),
            (
                "contacts",
                "lastModifiedOn",
                "2026-01-02T05:04:05+02:00",
                {"Q": 'lastmodifiedon:{"from":"2026-01-02T03:04:05.000Z"}'},
            ),
            (
                "satisfaction_ratings",
                "lastModifiedDate",
                date(2026, 1, 2),
                {"Q": 'lastmodifiedon:{"from":"2026-01-02T00:00:00.000Z"}', "OrderBy": "lastModifiedOn asc"},
            ),
            (
                "ticket_worklogs",
                "lastModifiedOn",
                datetime(2026, 1, 2, 3, 4, 5),
                {"updatedFromDate": "2026-01-02T03:04:05+00:00", "includeDeletedWorklogs": "true", "Q": None},
            ),
            # The first incremental sync has no watermark, so it reads every row.
            ("ticket_updates", "updatedOn", None, {"Q": None, "OrderBy": "ticketUpdateId asc"}),
        ],
    )
    def test_incremental_filter(self, schema: str, incremental_field: str, last_value: Any, expected: dict) -> None:
        result = _driver().run(
            schema,
            [_page([{"id": 1, "createdOn": "2026-01-01T00:00:00Z"}])],
            incremental_field=incremental_field,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        for name, value in expected.items():
            assert result.params(name) == [value]

    def test_full_refresh_sends_no_watermark(self) -> None:
        result = _driver().run(
            "tickets",
            [_page(_tickets(1, 1))],
            incremental_field="lastUpdatedOn",
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("Q") == [None]


class TestNormalizeSubdomain:
    @pytest.mark.parametrize(
        ("domain", "expected"),
        [
            ("acme", "acme"),
            ("  Acme-Support ", "acme-support"),
            ("acme.bolddesk.com", "acme"),
            ("https://acme.bolddesk.com/", "acme"),
            ("http://acme.bolddesk.com", "acme"),
        ],
    )
    def test_accepts(self, domain: str, expected: str) -> None:
        assert normalize_subdomain(domain) == expected

    @pytest.mark.parametrize(
        "domain",
        [
            "",
            "support.example.com",
            "acme.bolddesk.com.example.com",
            "acme.bolddesk.com/api",
            "user@acme",
            "acme:8080",
            "-acme",
        ],
    )
    def test_rejects_anything_but_one_label(self, domain: str) -> None:
        with pytest.raises(InvalidBoldDeskDomainError):
            normalize_subdomain(domain)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "schema_name", "expected_ok", "expected_path"),
        [
            (200, None, True, "/api/v1/tickets"),
            (401, None, False, "/api/v1/tickets"),
            # A valid key whose agent can't read tickets can still read other tables.
            (403, None, True, "/api/v1/tickets"),
            (403, "agents", False, "/api/v1/agents"),
            (404, None, False, "/api/v1/tickets"),
        ],
    )
    def test_probe_status(self, status: int, schema_name: str | None, expected_ok: bool, expected_path: str) -> None:
        body: dict[str, Any] = {
            "errors": [],
            "message": "Unauthorized" if status == 401 else "Access Denied",
            "statusCode": status,
        }
        with scripted_network(always(ScriptedResponse(status=status, json=body))) as network:
            ok, error = BoldDeskSource().validate_credentials(
                BoldDeskSourceConfig(domain="acme", api_key=API_KEY), team_id=1, schema_name=schema_name
            )

        assert ok is expected_ok
        assert (error is None) is expected_ok
        assert {request.path for request in network.requests_log} == {expected_path}
        assert {request.headers.get("x-api-key") for request in network.requests_log} == {API_KEY}

    def test_rejects_a_foreign_domain_without_a_request(self) -> None:
        with scripted_network(always(ScriptedResponse(json={}))) as network:
            ok, error = BoldDeskSource().validate_credentials(
                BoldDeskSourceConfig(domain="support.example.com", api_key=API_KEY), team_id=1
            )

        assert not ok
        assert error is not None and "subdomain" in error
        assert network.requests_log == []
