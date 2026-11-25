from datetime import date, datetime
from typing import Any

import pytest

from products.warehouse_sources.sources.justcall._config import JustCallSourceConfig
from products.warehouse_sources.sources.justcall.justcall import (
    JustCallResumeConfig,
    _format_cursor,
    validate_credentials,
)
from products.warehouse_sources.sources.justcall.source import JustCallSource
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)


def _driver() -> SourceDriver:
    return SourceDriver(JustCallSource(), JustCallSourceConfig(api_key="key", api_secret="secret"))


def _response(items: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "next_page_link": None})


class TestFormatCursor:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            ("", None),
            ("   ", None),
            ("2021-08-25", "2021-08-25"),
            ("2021-08-25 10:30:00", "2021-08-25"),
            ("2021-08-25T10:30:00", "2021-08-25"),
            (date(2021, 8, 25), "2021-08-25"),
            (datetime(2021, 8, 25, 10, 30, 0), "2021-08-25"),
        ],
    )
    def test_format_cursor(self, value: Any, expected: str | None) -> None:
        assert _format_cursor(value) == expected


class TestRequestParams:
    def test_incremental_request_carries_from_datetime(self) -> None:
        result = _driver().run(
            "calls",
            [_response([{"id": 1, "call_user_date": "2021-08-25"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2021-08-25",
        )

        assert result.raised is None
        assert result.rows == [{"id": 1, "call_user_date": "2021-08-25"}]
        assert result.requests[0].param("from_datetime") == "2021-08-25"
        assert result.requests[0].param("sort") == "datetime"


class TestPagination:
    @pytest.mark.parametrize("endpoint, page_size", [("sales_dialer_campaigns", 50), ("calls_ai", 20)])
    def test_endpoint_page_size_cap_drives_short_page_detection(self, endpoint: str, page_size: int) -> None:
        # A full page at the endpoint's lower cap must not be read as the last page.
        full_page = [{"id": i} for i in range(page_size)]
        result = _driver().run(endpoint, [_response(full_page), _response([{"id": page_size}])])

        assert result.raised is None
        assert len(result.rows) == page_size + 1
        assert len(result.requests) == 2
        assert result.params("per_page") == [str(page_size), str(page_size)]

    @pytest.mark.parametrize(
        "endpoint, expected_pages",
        [
            ("texts_tags", ["0"]),
            # No documented page-size cap, so a short page may just be the server's own cap.
            ("sales_dialer_contacts", ["0", "1"]),
        ],
    )
    def test_short_page_ends_walk_only_where_the_cap_is_documented(
        self, endpoint: str, expected_pages: list[str]
    ) -> None:
        result = _driver().run(endpoint, [_response([{"id": 1}, {"id": 2}]), _response([])])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2]
        assert result.params("page") == expected_pages

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run("calls", [_response([{"id": 9}])], resume_state=JustCallResumeConfig(page=5))

        assert result.raised is None
        assert result.params("page") == ["5"]


def _campaign_contacts_script(contacts: dict[str, list[dict[str, Any]]]) -> Any:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/v2.1/sales_dialer/campaigns":
            return _response([{"id": int(campaign_id), "name": f"Campaign {campaign_id}"} for campaign_id in contacts])
        assert request.path == "/v2.1/sales_dialer/campaigns/contacts"
        campaign_id = request.param("campaign_id")
        assert campaign_id is not None
        return _response(contacts[campaign_id] if request.param("page") == "0" else [])

    return respond


class TestCampaignContacts:
    def test_fans_out_over_campaigns_and_tags_rows_with_campaign(self) -> None:
        # The same contact in two campaigns must stay two rows, told apart by campaign_id.
        script = _campaign_contacts_script(
            {
                "1": [{"id": 10, "progress_status": "Dialed"}, {"id": 11}],
                "2": [{"id": 10, "progress_status": "Undialed"}],
            }
        )
        result = _driver().run("sales_dialer_campaign_contacts", script)

        assert result.raised is None
        assert result.rows == [
            {"id": 10, "progress_status": "Dialed", "campaign_id": 1},
            {"id": 11, "campaign_id": 1},
            {"id": 10, "progress_status": "Undialed", "campaign_id": 2},
        ]
        contact_requests = [r for r in result.requests if r.path.endswith("/contacts")]
        assert [(r.param("campaign_id"), r.param("page")) for r in contact_requests] == [
            ("1", "0"),
            ("1", "1"),
            ("2", "0"),
            ("2", "1"),
        ]
        assert {r.param("order") for r in contact_requests} == {"asc"}

    def test_resume_skips_completed_campaigns(self) -> None:
        script = _campaign_contacts_script({"1": [{"id": 10}], "2": [{"id": 20}]})
        first = _driver().run("sales_dialer_campaign_contacts", script)
        after_first_campaign = next(
            state for state in first.saved_states if state.fanout_state and state.fanout_state.get("completed")
        )

        resumed = _driver().run("sales_dialer_campaign_contacts", script, resume_state=after_first_campaign)

        assert resumed.raised is None
        assert resumed.rows == [{"id": 20, "campaign_id": 2}]
        assert "1" not in resumed.params("campaign_id")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("key", "secret") is expected

        assert network.requests_log[0].path == "/v2.1/phone-numbers"
        assert network.requests_log[0].param("page") == "0"
        assert network.requests_log[0].param("per_page") == "1"
        assert network.requests_log[0].headers["authorization"] == "key:secret"
