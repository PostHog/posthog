from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, route, scripted_network
from products.warehouse_sources.sources.simpro._config import SimproSourceConfig
from products.warehouse_sources.sources.simpro.settings import PAGE_SIZE
from products.warehouse_sources.sources.simpro.simpro import SimproResumeConfig
from products.warehouse_sources.sources.simpro.source import SimproSource

BUILD = "https://acme.simprosuite.com/staff/"


def _driver(company_id: str | None = "5") -> SourceDriver:
    return SourceDriver(SimproSource(), SimproSourceConfig(build=BUILD, api_key="key", company_id=company_id))


def _page(start: int, count: int) -> ScriptedResponse:
    return ScriptedResponse(
        json=[{"ID": i, "DateModified": "2024-03-01T10:00:00+10:00"} for i in range(start, start + count)]
    )


def test_archivable_endpoint_walks_active_then_archived_rows_and_stages_each_next_page() -> None:
    result = _driver().run(
        "sites",
        [_page(1, PAGE_SIZE), _page(1000, 3), _page(2000, 1)],
        should_use_incremental_field=False,
    )

    assert result.raised is None
    assert result.paths == ["/api/v1.0/companies/5/sites/"] * 3
    assert result.requests[0].origin == "https://acme.simprosuite.com"
    assert result.params("Archived") == ["false", "false", "true"]
    assert result.params("page") == ["1", "2", "1"]
    assert result.params("pageSize") == [str(PAGE_SIZE)] * 3
    assert result.params("orderby") == ["ID"] * 3
    assert result.params("DateModified") == [None] * 3
    assert all("Archived" in (columns or "").split(",") for columns in result.params("columns"))
    assert len(result.rows) == PAGE_SIZE + 4
    assert {row["CompanyID"] for row in result.rows} == {5}
    assert result.committed_states == [
        SimproResumeConfig(company_id=5, archived=False, page=2),
        SimproResumeConfig(company_id=5, archived=True, page=1),
        SimproResumeConfig(company_id=5, archived=True, page=2),
    ]


@pytest.mark.parametrize("company_id", [None, "", "  "])
def test_blank_company_id_fans_out_over_every_company_in_the_build(company_id: str | None) -> None:
    result = _driver(company_id=company_id).run(
        "contacts",
        route(
            {
                "/companies/": [ScriptedResponse(json=[{"ID": 0, "Name": "Head office"}, {"ID": 3, "Name": "North"}])],
                "/companies/0/contacts/": [_page(1, 2)],
                "/companies/3/contacts/": [_page(1, 1)],
            }
        ),
        should_use_incremental_field=False,
    )

    assert result.raised is None
    assert result.paths == [
        "/api/v1.0/companies/",
        "/api/v1.0/companies/0/contacts/",
        "/api/v1.0/companies/3/contacts/",
    ]
    assert result.params("Archived") == [None, None, None]
    assert [(row["CompanyID"], row["ID"]) for row in result.rows] == [(0, 1), (0, 2), (3, 1)]


@pytest.mark.parametrize(
    ("schema", "watermark", "should_use_incremental_field", "expected"),
    [
        # 01:00 at UTC+10 is the previous day in UTC, and the filter starts one more day earlier.
        ("invoices", "2024-03-10T01:00:00+10:00", True, "ge(2024-03-08)"),
        ("invoices", datetime(2024, 3, 10, 12, tzinfo=UTC), True, "ge(2024-03-09)"),
        ("invoices", None, True, None),
        ("invoices", "2024-03-10T01:00:00+10:00", False, None),
    ],
)
def test_incremental_sync_filters_by_day_before_the_watermark(
    schema: str, watermark: Any, should_use_incremental_field: bool, expected: str | None
) -> None:
    result = _driver().run(
        schema,
        [_page(1, 1)],
        incremental_field="DateModified",
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.params("DateModified") == [expected]


def test_resume_continues_from_the_saved_pass_and_page() -> None:
    result = _driver().run(
        "company_customers",
        [_page(1, 2)],
        should_use_incremental_field=False,
        resume_state=SimproResumeConfig(company_id=5, archived=True, page=3),
    )

    assert result.raised is None
    assert result.params("Archived") == ["true"]
    assert result.params("page") == ["3"]


@pytest.mark.parametrize(
    ("build", "company_id", "script", "expected", "expected_host"),
    [
        ("acme", None, [ScriptedResponse(json=[{"ID": 0}])], (True, None), "acme.simprosuite.com"),
        (
            "https://ACME.simprocloud.com/staff/",
            "0",
            [ScriptedResponse(json=[{"ID": 0}])],
            (True, None),
            "acme.simprocloud.com",
        ),
        ("acme.example.com", None, [], (False, "Enter your Simpro build name or URL"), None),
        ("simprosuite.com", None, [], (False, "Enter your Simpro build name or URL"), None),
        ("acme.simprosuite.com.example.com", None, [], (False, "Enter your Simpro build name or URL"), None),
        ("evilsimprosuite.com", None, [], (False, "Enter your Simpro build name or URL"), None),
        ("acme.simprosuite.com", "north", [], (False, "The company ID must be a number"), None),
        (
            "acme.simprosuite.com",
            None,
            [ScriptedResponse(status=401, json={"errors": [{"path": None, "message": "Unauthorized", "value": None}]})],
            (False, "Simpro rejected the API key"),
            "acme.simprosuite.com",
        ),
        (
            "acme.simprosuite.com",
            "2",
            [ScriptedResponse(status=403, json={"errors": []})],
            (True, None),
            "acme.simprosuite.com",
        ),
        (
            "acme.simprosuite.com",
            None,
            [ScriptedResponse(status=403, json={"errors": []})],
            (False, "can't list the companies in your build"),
            "acme.simprosuite.com",
        ),
        (
            "acme.simprosuite.com",
            "7",
            [ScriptedResponse(json=[{"ID": 0}, {"ID": 1}])],
            (False, "Company 7 doesn't exist in this build"),
            "acme.simprosuite.com",
        ),
        (
            "acme.simprosuite.com",
            None,
            [ScriptedResponse(body=b"<html>Log in</html>", headers={"Content-Type": "text/html"})],
            (False, "didn't answer like a Simpro build"),
            "acme.simprosuite.com",
        ),
    ],
)
def test_validate_credentials(
    build: str,
    company_id: str | None,
    script: list[ScriptedResponse],
    expected: tuple[bool, str | None],
    expected_host: str | None,
) -> None:
    config = SimproSourceConfig(build=build, api_key="key", company_id=company_id)

    with scripted_network(script) as network:
        ok, message = SimproSource().validate_credentials(config, team_id=1)

    expected_ok, expected_message = expected
    assert ok is expected_ok
    if expected_message is None:
        assert message is None
    else:
        assert message is not None and expected_message in message
    assert len(network.requests_log) == len(script)
    for request in network.requests_log:
        assert request.origin == f"https://{expected_host}"
        assert request.path == "/api/v1.0/companies/"
        assert request.headers.get("authorization") == "Bearer key"
