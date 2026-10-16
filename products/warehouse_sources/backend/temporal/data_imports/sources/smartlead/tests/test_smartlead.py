from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartlead import (
    SmartleadSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.smartlead import (
    SmartleadResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.source import SmartleadSource


def _run(endpoint: str, script: Script, **inputs: Any) -> DriveResult:
    return SourceDriver(SmartleadSource(), SmartleadSourceConfig(api_key="key")).run(endpoint, script, **inputs)


def _json(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


def _accounts(count: int, start: int = 0) -> list[dict[str, Any]]:
    return [{"id": start + i, "from_email": f"a{start + i}@example.com"} for i in range(count)]


class TestSmartleadSource:
    def test_offset_pagination_walks_until_short_page(self) -> None:
        result = _run("email_accounts", [_json(_accounts(PAGE_SIZE)), _json(_accounts(1, start=PAGE_SIZE))])

        assert len(result.rows) == PAGE_SIZE + 1
        assert len(result.requests) == 2
        assert result.requests[0].url.startswith("https://server.smartlead.ai/api/v1/email-accounts/")
        assert result.requests[0].param("offset") == "0"
        assert result.requests[0].param("limit") == str(PAGE_SIZE)
        assert result.requests[1].param("offset") == str(PAGE_SIZE)

    def test_campaigns_single_page_never_paginates(self) -> None:
        # The campaign list is unpaginated. An offset paginator here would refetch the same full
        # array forever, because a full-length page never triggers the short-page stop.
        result = _run("campaigns", [_json([{"id": i} for i in range(PAGE_SIZE * 2)])])

        assert len(result.rows) == PAGE_SIZE * 2
        assert len(result.requests) == 1
        assert result.requests[0].path == "/api/v1/campaigns/"
        assert result.requests[0].param("offset") is None

    def test_enveloped_body_on_list_endpoint_fails_loud(self) -> None:
        # The docs show an `{ok, data}` envelope for /client/ while the live API historically
        # returns a bare array. Whichever way the API answers, a non-list body must raise
        # instead of silently syncing a garbage row.
        result = _run("clients", [_json({"ok": True, "data": [{"id": 1}]})])

        assert isinstance(result.raised, ValueError)
        assert "Required a list response body" in str(result.raised)

    def test_resumes_from_saved_offset(self) -> None:
        result = _run(
            "email_accounts",
            [_json(_accounts(1, start=PAGE_SIZE))],
            resume_state=SmartleadResumeConfig(next_offset=PAGE_SIZE),
        )

        assert [r["id"] for r in result.rows] == [PAGE_SIZE]
        assert len(result.requests) == 1
        assert result.requests[0].param("offset") == str(PAGE_SIZE)


class TestSmartleadFanout:
    def test_leads_fan_out_paginates_per_campaign_and_injects_campaign_id(self) -> None:
        result = _run(
            "campaign_leads",
            [
                _json([{"id": 11}, {"id": 22}]),
                _json(
                    {"total_leads": str(PAGE_SIZE + 1), "data": [{"campaign_lead_map_id": i} for i in range(PAGE_SIZE)]}
                ),
                _json({"total_leads": str(PAGE_SIZE + 1), "data": [{"campaign_lead_map_id": PAGE_SIZE}]}),
                _json({"total_leads": "1", "data": [{"campaign_lead_map_id": 9000}]}),
            ],
        )

        # Parent listed once (no pagination), campaign 11 paged twice, campaign 22 once.
        assert result.paths == [
            "/api/v1/campaigns/",
            "/api/v1/campaigns/11/leads",
            "/api/v1/campaigns/11/leads",
            "/api/v1/campaigns/22/leads",
        ]
        assert result.requests[0].param("offset") is None
        assert result.params("offset")[1:] == ["0", str(PAGE_SIZE), "0"]

        assert len(result.rows) == PAGE_SIZE + 2
        # Lead rows don't carry their campaign id; the fan-out injects it for the composite key.
        assert result.rows[0]["campaign_id"] == 11
        assert result.rows[-1]["campaign_id"] == 22

    def test_analytics_object_body_becomes_one_row_per_campaign(self) -> None:
        result = _run(
            "campaign_analytics",
            [_json([{"id": 11}]), _json({"campaign_name": "Q1", "total_sent": 10})],
        )

        assert result.rows == [{"campaign_name": "Q1", "total_sent": 10, "campaign_id": 11}]

    def test_fan_out_resumes_completed_and_current_campaign(self) -> None:
        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/campaigns/"):
                return _json([{"id": 11}, {"id": 22}])
            return _json({"total_leads": "1", "data": [{"campaign_lead_map_id": 1}]})

        result = _run(
            "campaign_leads",
            script,
            resume_state=SmartleadResumeConfig(
                completed=["/campaigns/11/leads"],
                current="/campaigns/22/leads",
                child_state={"offset": PAGE_SIZE},
            ),
        )

        assert result.paths == ["/api/v1/campaigns/", "/api/v1/campaigns/22/leads"]
        assert result.params("offset")[1] == str(PAGE_SIZE)


class TestValidateCredentials:
    def test_probe_carries_key_in_query_and_never_follows_redirects(self) -> None:
        redirect = ScriptedResponse(status=302, headers={"Location": "https://attacker.example.com/capture"})
        with scripted_network(always(redirect)) as network:
            validate_credentials("key")

        assert [request.origin for request in network.requests_log] == ["https://server.smartlead.ai"]
        request = network.requests_log[0]
        assert request.path == "/api/v1/email-accounts/"
        assert (request.param("api_key"), request.param("offset"), request.param("limit")) == ("key", "0", "1")
        # The tracked session must mask the key in logs and captured samples.
        assert network.session_options[0]["redact_values"] == ("key",)
