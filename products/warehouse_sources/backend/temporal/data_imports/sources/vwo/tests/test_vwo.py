from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vwo import VWOSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vwo.source import VWOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.vwo.vwo import VWOResumeConfig


def driver() -> SourceDriver:
    return SourceDriver(VWOSource(), VWOSourceConfig(api_token="test-token", account_id="123"))


def collection(rows: list[dict[str, Any]], wrapped: bool = True) -> ScriptedResponse:
    return ScriptedResponse(json={"_data": {"partialCollection": rows} if wrapped else rows})


@pytest.mark.parametrize(
    "endpoint,wrapped", [("campaigns", True), ("campaigns", False), ("feature_flags", True), ("metric_reports", True)]
)
def test_collection_walks_all_pages_and_commits_before_handoff(endpoint: str, wrapped: bool) -> None:
    result = driver().run(
        endpoint,
        [collection([{"id": i} for i in range(25)], wrapped), collection([{"id": 25}], wrapped)],
    )
    assert result.raised is None
    assert [row["id"] for row in result.rows] == list(range(26))
    assert result.params("offset") == ["0", "25"]
    assert result.params("limit") == ["25", "25"]
    assert result.committed_states == [VWOResumeConfig(paginator_state={"offset": 25})]
    assert result.requests[0].headers["token"] == "test-token"
    assert result.requests[0].origin == "https://app.wingify.com"


def test_resume_uses_the_next_offset() -> None:
    result = driver().run(
        "campaigns", [collection([{"id": 55}])], resume_state=VWOResumeConfig(paginator_state={"offset": 50})
    )
    assert result.raised is None
    assert result.params("offset") == ["50"]
    assert result.rows[0]["id"] == 55


@pytest.mark.parametrize("endpoint", ["variations", "goals", "campaign_sections"])
def test_campaign_children_keep_parent_ids_and_resume_completed_parents(endpoint: str) -> None:
    suffix = "sections" if endpoint == "campaign_sections" else endpoint
    child_row = {"id": 1, "sectionId": None} if endpoint == "variations" else {"id": 1}
    script = route(
        {
            "/accounts/123/campaigns": [collection([{"id": 11}, {"id": 12}], False)],
            f"/accounts/123/campaigns/11/{suffix}": [collection([child_row], False)],
            f"/accounts/123/campaigns/12/{suffix}": [collection([{"id": 1}], False)],
        }
    )
    result = driver().run(endpoint, script)
    assert result.raised is None
    assert [(row["campaign_id"], row["id"]) for row in result.rows] == [(11, 1), (12, 1)]
    assert all(request.param("limit") is None for request in result.requests[1:])
    if endpoint == "variations":
        assert [row["sectionId"] for row in result.rows] == [0, 0]
    assert result.committed_states
    resumed = driver().run(
        endpoint,
        route(
            {
                "/accounts/123/campaigns": [collection([{"id": 11}, {"id": 12}], False)],
                f"/accounts/123/campaigns/12/{suffix}": [collection([{"id": 1}], False)],
            }
        ),
        resume_state=result.committed_states[0],
    )
    assert resumed.raised is None
    assert [(row["campaign_id"], row["id"]) for row in resumed.rows] == [(12, 1)]


@pytest.mark.parametrize("empty", [[], {}, None])
def test_report_empty_collection_terminates(empty: Any) -> None:
    result = driver().run(
        "metric_reports", [ScriptedResponse(json={"_data": {"partialCollection": empty, "totalCount": "0"}})]
    )
    assert result.raised is None
    assert result.rows == []
    assert len(result.requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"_errors": [{"code": 401, "message": "Authentication Failed"}]},
        {"_data": {"unexpected": []}},
        {"_data": ["bad row"]},
    ],
)
def test_invalid_envelopes_fail_instead_of_replacing_with_empty_data(body: dict[str, Any]) -> None:
    result = driver().run("campaigns", [ScriptedResponse(json=body)])
    assert isinstance(result.raised, ValueError)
    assert result.rows == []


@pytest.mark.parametrize(
    "endpoint,field,singleton",
    [
        ("accounts", "createdOn", True),
        ("campaigns", "createdOn", False),
        ("metric_reports", "createdOn", False),
        ("websites", "createdAt", False),
    ],
)
def test_creation_times_keep_raw_fields_and_produce_stable_partitions(
    endpoint: str, field: str, singleton: bool
) -> None:
    row = {"id": 7, field: 1704067200, "lastUpdatedAt": 1710000000, "nested": {"value": None}}
    result = driver().run(endpoint, [ScriptedResponse(json={"_data": row}) if singleton else collection([row], False)])
    assert result.raised is None
    assert result.rows == [{**row, "created_at": datetime(2024, 1, 1, tzinfo=UTC)}]


def test_deleted_campaign_does_not_stop_other_children() -> None:
    result = driver().run(
        "goals",
        [
            collection([{"id": 11}, {"id": 12}], False),
            ScriptedResponse(status=404, json={}),
            collection([{"id": 1}], False),
        ],
    )
    assert result.raised is None
    assert result.rows == [{"id": 1, "campaign_id": 12}]
