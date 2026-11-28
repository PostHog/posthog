from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests
from structlog.testing import capture_logs

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network
from products.warehouse_sources.sources.virtuous import virtuous
from products.warehouse_sources.sources.virtuous._config import VirtuousSourceConfig
from products.warehouse_sources.sources.virtuous.source import VirtuousSource
from products.warehouse_sources.sources.virtuous.virtuous import (
    VirtuousResumeConfig,
    modified_since,
    validate_credentials,
)


def _driver() -> SourceDriver:
    return SourceDriver(VirtuousSource(), VirtuousSourceConfig(api_key="test-key"))


def _page(first_id: int, count: int, total: int) -> ScriptedResponse:
    return ScriptedResponse(json={"list": [{"id": first_id + i} for i in range(count)], "total": total})


def _last_modified_condition(value: str) -> list[dict[str, Any]]:
    return [{"conditions": [{"parameter": "Last Modified Date", "operator": "OnOrAfter", "value": value}]}]


class TestPagination:
    @pytest.mark.parametrize(
        ("schema", "method", "path", "take", "expected_body"),
        [
            (
                "contacts",
                "POST",
                "/api/Contact/Query/FullContact",
                500,
                {"includeArchived": True, "groups": [], "sortBy": "Id", "descending": False},
            ),
            ("tags", "GET", "/api/Tag", 1000, None),
            ("segments", "POST", "/api/Segment/Search", 1000, {"search": ""}),
        ],
    )
    def test_walks_skip_pages_until_total_and_stages_offset_before_each_page(
        self, schema: str, method: str, path: str, take: int, expected_body: dict[str, Any] | None
    ) -> None:
        result = _driver().run(schema, [_page(1, take, take + 2), _page(take + 1, 2, take + 2)])

        assert result.raised is None
        assert [request.method for request in result.requests] == [method, method]
        assert result.paths == [path, path]
        assert result.params("skip") == ["0", str(take)]
        assert result.params("take") == [str(take), str(take)]
        assert [request.json() for request in result.requests] == [expected_body, expected_body]
        assert result.requests[0].headers["authorization"] == "Bearer test-key"
        assert len(result.rows) == take + 2
        assert result.committed_states == [VirtuousResumeConfig(skip=take)]

    def test_resume_starts_at_the_saved_skip(self) -> None:
        result = _driver().run(
            "gifts",
            [_page(1001, 3, 1003)],
            resume_state=VirtuousResumeConfig(skip=1000),
        )

        assert result.raised is None
        assert result.paths == ["/api/Gift/Query/FullGift"]
        assert result.params("skip") == ["1000"]
        assert len(result.rows) == 3


def test_communications_fanout_resumes_on_the_next_child_page() -> None:
    campaigns = ScriptedResponse(json={"list": [{"campaignId": 7}, {"campaignId": 8}], "total": 2})
    first_page = [{"communicationId": offset + 1, "campaignId": 7} for offset in range(1000)]
    remaining_row = {"communicationId": 1001, "campaignId": 7}
    next_campaign_row = {"communicationId": 1002, "campaignId": 8}
    last_page = ScriptedResponse(json={"list": [remaining_row], "total": 1001})
    next_campaign_page = ScriptedResponse(json={"list": [next_campaign_row], "total": 1})
    result = _driver().run(
        "communications",
        [campaigns, ScriptedResponse(json={"list": first_page, "total": 1001}), last_page, next_campaign_page],
    )

    assert result.raised is None
    assert result.rows == [*first_page, remaining_row, next_campaign_row]

    resumed = _driver().run(
        "communications", [campaigns, last_page, next_campaign_page], resume_state=result.committed_states[0]
    )

    assert resumed.raised is None
    assert resumed.paths == [
        "/api/Campaign/Query",
        "/api/Communication/ByCampaign/7",
        "/api/Communication/ByCampaign/8",
    ]
    assert resumed.params("skip") == ["0", "1000", "0"]
    assert resumed.rows == [remaining_row, next_campaign_row]


@pytest.mark.parametrize("total", [1000, None])
def test_communications_page_cap_fails_instead_of_publishing_an_incomplete_refresh(
    monkeypatch: pytest.MonkeyPatch, total: int | None
) -> None:
    monkeypatch.setattr(virtuous, "COMMUNICATIONS_MAX_PAGES", 1)
    rows = [{"communicationId": offset + 1} for offset in range(1000)]

    with capture_logs() as logs:
        result = _driver().run(
            "communications",
            [
                ScriptedResponse(json={"list": [{"campaignId": 7}], "total": 1}),
                ScriptedResponse(json={"list": rows, "total": total}),
            ],
        )

    assert result.paths == ["/api/Campaign/Query", "/api/Communication/ByCampaign/7"]
    cap_logs = [entry for entry in logs if entry["event"] == "virtuous_communications_page_cap_reached"]
    if total is None:
        assert isinstance(result.raised, ValueError)
        assert result.rows == []
        assert [entry["campaign_id"] for entry in cap_logs] == ["7"]
    else:
        assert result.raised is None
        assert result.rows == rows
        assert cap_logs == []


class TestIncrementalRequestShaping:
    @pytest.mark.parametrize(
        ("schema", "inputs", "expected_groups"),
        [
            (
                "gifts",
                {"incremental_field": "modifiedDateTimeUtc", "db_incremental_field_last_value": "2024-03-10T00:30:00Z"},
                _last_modified_condition("2024-03-09"),
            ),
            (
                "volunteer_opportunities",
                {
                    "incremental_field": "modifiedDateTimeUtc",
                    "db_incremental_field_last_value": datetime(2024, 1, 1, 23, 59, tzinfo=UTC),
                },
                _last_modified_condition("2023-12-31"),
            ),
            # First incremental sync: no watermark yet, so every record is read.
            (
                "gifts",
                {"incremental_field": "modifiedDateTimeUtc", "db_incremental_field_last_value": None},
                [],
            ),
            (
                "gifts",
                {
                    "incremental_field": "modifiedDateTimeUtc",
                    "should_use_incremental_field": False,
                    "db_incremental_field_last_value": "2024-03-10T00:30:00Z",
                },
                [],
            ),
            # Gift designations have no "Last Modified Date" condition, so a stray watermark is ignored.
            (
                "gift_designations",
                {"incremental_field": "modifiedDateTimeUtc", "db_incremental_field_last_value": "2024-03-10T00:30:00Z"},
                [],
            ),
        ],
    )
    def test_watermark_becomes_a_last_modified_condition_only_for_incremental_syncs(
        self, schema: str, inputs: dict[str, Any], expected_groups: list[dict[str, Any]]
    ) -> None:
        result = _driver().run(schema, [_page(1, 1, 1)], **inputs)

        assert result.raised is None
        body = result.requests[0].json()
        assert body["groups"] == expected_groups
        assert (body["sortBy"], body["descending"]) == ("Id", False)

    @pytest.mark.parametrize(
        ("last_value", "expected"),
        [
            (datetime(2024, 3, 1, 0, 0, tzinfo=UTC), "2024-02-29"),
            (date(2024, 1, 1), "2023-12-31"),
            ("2024-06-15T12:34:56.789Z", "2024-06-14"),
            ("2024-06-15", "2024-06-14"),
        ],
    )
    def test_modified_since_starts_one_day_before_the_watermark(self, last_value: Any, expected: str) -> None:
        assert modified_since(last_value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_fragment"),
        [
            (200, True, None),
            (401, False, "Virtuous rejected the API key"),
            (403, False, "permission group"),
            (500, False, "unexpected status (500)"),
        ],
    )
    def test_maps_probe_status_to_result(
        self, status_code: int, expected_valid: bool, expected_fragment: str | None
    ) -> None:
        body = {"message": "Authorization has been denied for this request."} if status_code == 401 else {}
        with scripted_network(always(ScriptedResponse(status=status_code, json=body))) as network:
            valid, message = validate_credentials("test-key")

        assert valid is expected_valid
        if expected_fragment is None:
            assert message is None
        else:
            assert expected_fragment in (message or "")
        assert network.requests_log[0].path == "/api/Organization/Current"
        assert network.requests_log[0].headers["authorization"] == "Bearer test-key"

    def test_transport_error_reports_unreachable_instead_of_raising(self) -> None:
        with scripted_network(always(requests.ConnectionError("dns failure"))):
            valid, message = validate_credentials("test-key")

        assert valid is False
        assert "Couldn't reach Virtuous" in (message or "")

    def test_non_ascii_key_fails_without_a_request(self) -> None:
        with scripted_network([]) as network:
            valid, message = validate_credentials("bad中key")

        assert valid is False
        assert "unsupported character" in (message or "")
        assert network.requests_log == []
