from datetime import UTC, datetime
from typing import Any, Optional

import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.impact import ImpactSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.impact import (
    ImpactResumeConfig,
    _resume_index,
    _safe_int,
    _to_datetime,
    _windows_for_actions,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.settings import (
    IMPACT_API_VERSION_14,
    IMPACT_API_VERSION_LEGACY,
    IMPACT_VERSION_HEADER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.source import ImpactSource


def _driver() -> SourceDriver:
    return SourceDriver(ImpactSource(), ImpactSourceConfig(account_sid="sid", auth_token="token"))


class TestToDatetime:
    @parameterized.expand(
        [
            ("none", None, None),
            ("naive_string", "2024-01-01T00:00:00", datetime(2024, 1, 1, tzinfo=UTC)),
            ("z_string", "2024-01-01T00:00:00Z", datetime(2024, 1, 1, tzinfo=UTC)),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_to_datetime(self, _name: str, value: Any, expected: Optional[datetime]) -> None:
        assert _to_datetime(value) == expected


class TestSafeInt:
    @parameterized.expand(
        [
            ("string", "3", 3),
            ("int", 3, 3),
            ("none", None, None),
            ("garbage", "abc", None),
        ]
    )
    def test_safe_int(self, _name: str, value: Any, expected: Optional[int]) -> None:
        assert _safe_int(value) == expected


class TestWindowsForActions:
    @time_machine.travel("2024-06-01", tick=False)
    def test_full_refresh_backfills_max_lookback(self) -> None:
        windows = _windows_for_actions(False, None)
        assert windows[0][0] == datetime(2021, 6, 2, tzinfo=UTC)
        assert windows[-1][1] == datetime(2024, 6, 1, tzinfo=UTC)

    @time_machine.travel("2024-06-01", tick=False)
    def test_future_cursor_yields_no_windows(self) -> None:
        assert _windows_for_actions(True, datetime(2025, 1, 1, tzinfo=UTC)) == []


class TestResumeIndex:
    def test_stale_bookmark_falls_back_to_start(self) -> None:
        window = (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))
        work_items = [(window, 1)]
        resume = ImpactResumeConfig(campaign_id=999, window_start=window[0].isoformat())
        assert _resume_index(work_items, resume) == 0


class TestApiVersionHeader:
    @parameterized.expand([(IMPACT_API_VERSION_LEGACY, False), (IMPACT_API_VERSION_14, True)])
    def test_get_rows_threads_version_to_session(self, api_version: str, expects_header: bool) -> None:
        result = _driver().run(
            "Campaigns", [ScriptedResponse(json={"Campaigns": [], "@numpages": "1"})], api_version=api_version
        )
        assert result.raised is None
        assert (result.requests[0].headers.get(IMPACT_VERSION_HEADER.lower()) == api_version) is expects_header


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("sid", "token") is expected
        assert network.requests_log[0].path == "/Advertisers/sid/Campaigns"
        assert network.requests_log[0].param("PageSize") == "1"

    def test_exception_is_false(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("sid", "token") is False
        assert {request.path for request in network.requests_log} == {"/Advertisers/sid/Campaigns"}


class TestGetRowsSimple:
    def test_multi_page_endpoint_saves_state_per_page(self) -> None:
        result = _driver().run(
            "Campaigns",
            [
                ScriptedResponse(json={"Campaigns": [{"Id": 1}], "@numpages": "2"}),
                ScriptedResponse(json={"Campaigns": [{"Id": 2}], "@numpages": "2"}),
            ],
        )
        assert result.raised is None
        assert result.items == [[{"Id": 1}], [{"Id": 2}]]
        assert result.params("Page") == ["1", "2"]
        assert result.saved_states == [ImpactResumeConfig(page=1), ImpactResumeConfig(page=2)]

    def test_incremental_param_sent_when_using_incremental_field(self) -> None:
        result = _driver().run(
            "MediaPartners",
            [ScriptedResponse(json={"Partners": [], "@numpages": "1"})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00",
        )
        assert result.raised is None
        assert result.requests[0].param("startDate") == "2024-01-01T00:00:00Z"


class TestGetRowsActions:
    @time_machine.travel("2024-06-01", tick=False)
    def test_no_campaigns_yields_nothing(self) -> None:
        result = _driver().run("Actions", [ScriptedResponse(json={"Campaigns": [], "@numpages": "1"})])
        assert result.raised is None
        assert result.items == []
        assert result.paths == ["/Advertisers/sid/Campaigns"]

    @time_machine.travel("2024-06-01", tick=False)
    def test_resume_skips_campaigns_before_the_bookmark(self) -> None:
        # An incremental cursor collapses the run to a single window, starting exactly at the
        # cursor value. Bookmarking campaign 20 (the middle of three) re-fetches it plus
        # everything after (merge dedupes the re-fetch); campaign 10 is skipped entirely.
        last_value = datetime(2024, 5, 30, tzinfo=UTC)
        result = _driver().run(
            "Actions",
            route(
                {
                    "/Campaigns": [
                        ScriptedResponse(json={"Campaigns": [{"Id": 10}, {"Id": 20}, {"Id": 30}], "@numpages": "1"})
                    ],
                    "/Actions": [
                        ScriptedResponse(json={"Actions": [], "@numpages": "1"}),
                        ScriptedResponse(json={"Actions": [], "@numpages": "1"}),
                    ],
                }
            ),
            resume_state=ImpactResumeConfig(campaign_id=20, window_start=last_value.isoformat()),
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )
        assert result.raised is None
        assert result.params("CampaignId") == [None, "20", "30"]


class TestGetRowsNested:
    def test_detailed_line_items_use_their_own_array(self) -> None:
        invoices = {
            "Invoices": [
                {
                    "Id": "INV-1",
                    "LineItems": [{"CampaignId": 10}],
                    "DetailedLineItems": [{"ProgramId": 99}],
                }
            ],
            "@numpages": "1",
        }
        result = _driver().run("InvoiceDetailedLineItems", [ScriptedResponse(json=invoices)])
        assert result.raised is None
        assert result.rows == [{"ProgramId": 99, "InvoiceId": "INV-1", "LineNumber": 1}]

    def test_invoice_without_the_array_is_skipped(self) -> None:
        invoices = {"Invoices": [{"Id": "INV-1"}, {"Id": "INV-2", "LineItems": []}], "@numpages": "1"}
        result = _driver().run("InvoiceLineItems", [ScriptedResponse(json=invoices)])
        assert result.raised is None
        assert result.items == []


class TestGetRowsContractsFanout:
    def test_campaign_id_goes_in_path_and_is_injected_on_rows(self) -> None:
        result = _driver().run(
            "Contracts",
            [
                ScriptedResponse(json={"Campaigns": [{"Id": 10}, {"Id": 20}], "@numpages": "1"}),
                ScriptedResponse(json={"Contracts": [{"Id": "C-1"}], "@numpages": "1"}),
                ScriptedResponse(json={"Contracts": [{"Id": "C-1"}], "@numpages": "1"}),
            ],
        )
        assert result.raised is None
        assert result.paths[1:] == [
            "/Advertisers/sid/Campaigns/10/Contracts",
            "/Advertisers/sid/Campaigns/20/Contracts",
        ]
        # Contracts is not scoped by a query param — the campaign lives in the path only.
        assert result.params("CampaignId") == [None, None, None]
        injected = {row["CampaignId"] for row in result.rows}
        assert injected == {10, 20}


class TestGetRowsSurveyResponses:
    @parameterized.expand(
        [
            (
                "full_walk",
                None,
                [
                    "/Advertisers/sid/Programs/10/Surveys/1/Responses",
                    "/Advertisers/sid/Programs/10/Surveys/2/Responses",
                ],
                [{"Id": 5, "CampaignId": 10, "SurveyId": 1}, {"Id": 6, "CampaignId": 10, "SurveyId": 2}],
            ),
            (
                "resume_after_bookmarked_survey",
                ImpactResumeConfig(campaign_id=10, survey_id=1),
                ["/Advertisers/sid/Programs/10/Surveys/2/Responses"],
                [{"Id": 6, "CampaignId": 10, "SurveyId": 2}],
            ),
            ("resume_after_completed_program", ImpactResumeConfig(campaign_id=20), [], []),
        ]
    )
    def test_walks_programs_and_surveys(
        self,
        _name: str,
        resume_state: Optional[ImpactResumeConfig],
        expected_response_paths: list[str],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(
            "SurveyResponses",
            route(
                {
                    "/Campaigns": [ScriptedResponse(json={"Campaigns": [{"Id": 20}, {"Id": 10}], "@numpages": "1"})],
                    "/Programs/10/Surveys": [ScriptedResponse(json={"Surveys": [{"Id": 2}, {"Id": 1}]})],
                    "/Programs/20/Surveys": [ScriptedResponse(status=404)],
                    "/Surveys/1/Responses": [ScriptedResponse(json={"Responses": [{"Id": 5}]})],
                    "/Surveys/2/Responses": [ScriptedResponse(json={"Responses": [{"Id": 6}]})],
                }
            ),
            resume_state=resume_state,
        )
        assert result.raised is None
        assert [path for path in result.paths if path.endswith("/Responses")] == expected_response_paths
        assert "/Advertisers/sid/Programs/20/Surveys" in result.paths
        assert result.rows == expected_rows
        assert result.saved_states[-1] == ImpactResumeConfig(campaign_id=21)


class TestImpactSourceResponse:
    @parameterized.expand(
        [
            ("Campaigns", ["Id"], None),
            ("MediaPartners", ["Id"], None),
            ("Invoices", ["Id"], None),
            ("Actions", ["Id"], "EventDate"),
            ("ActionUpdates", ["Id"], "ActionDate"),
            ("Contracts", ["CampaignId", "Id"], None),
            ("InvoiceLineItems", ["InvoiceId", "LineNumber"], None),
            ("InvoiceDetailedLineItems", ["InvoiceId", "LineNumber"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_pks: list[str], partition_key: Optional[str]) -> None:
        if endpoint in {"Actions", "ActionUpdates", "Contracts", "Campaigns"}:
            response_key = "Campaigns"
        elif endpoint.startswith("Invoice"):
            response_key = "Invoices"
        else:
            response_key = "Partners"
        result = _driver().run(endpoint, [ScriptedResponse(json={response_key: [], "@numpages": "1"})])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
