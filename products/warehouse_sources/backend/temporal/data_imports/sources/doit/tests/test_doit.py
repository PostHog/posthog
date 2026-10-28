from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit import (
    LIST_REPORTS_TIMEOUT_SECONDS,
    REPORT_TIMEOUT_SECONDS,
    doit_list_reports,
    doit_source,
    resolve_report_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.doit.source import DoItSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.doit import DoItSourceConfig

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit"

CONFIG = DoItSourceConfig(api_key="key")


def _response(payload: Any, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.text = "body"
    return response


class TestResolveReportId:
    @pytest.mark.parametrize("schema_metadata", [None, {}, {"report_id": None}])
    def test_falls_back_to_name_lookup(self, schema_metadata: dict | None) -> None:
        with scripted_network(
            [ScriptedResponse(json={"reports": [{"id": "r7", "reportName": "Cost by product"}]})]
        ) as network:
            assert resolve_report_id(CONFIG, "cost_by_product", schema_metadata) == "r7"
        assert [request.path for request in network.requests_log] == ["/analytics/v1/reports"]

    def test_raises_when_no_report_matches_the_name(self) -> None:
        with scripted_network([ScriptedResponse(json={"reports": [{"id": "r7", "reportName": "Cost by product"}]})]):
            with pytest.raises(Exception, match="Report no longer exists"):
                resolve_report_id(CONFIG, "deleted_report", None)


class TestDoitListReports:
    def test_returns_raw_and_normalized_names(self) -> None:
        with scripted_network(
            [
                ScriptedResponse(
                    json={
                        "reports": [
                            {"id": "r1", "reportName": "Cost by product"},
                            {"id": "r2", "reportName": "   "},
                            {"id": "r3"},
                        ]
                    }
                )
            ]
        ):
            reports = doit_list_reports(CONFIG)

        assert [(r.id, r.name, r.report_name) for r in reports] == [("r1", "cost_by_product", "Cost by product")]

    def test_non_200_surfaces_the_status_code(self) -> None:
        # `DOIT_RETRY` sets raise_on_status=False, so an exhausted 5xx lands here as a response;
        # without the guard it became a JSON/key error with the status lost.
        with scripted_network(always(ScriptedResponse(status=500, body=b"body"))):
            with pytest.raises(Exception, match="failed with status: 500"):
                doit_list_reports(CONFIG)


class TestRequestTimeouts:
    # An unbounded request holds the worker until the activity's start-to-close budget expires,
    # leaving the schema stuck in "Running" for a day or more.
    def test_list_reports_is_bounded(self) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response({"reports": []})
            doit_list_reports(CONFIG)

        assert mock_session.return_value.get.call_args.kwargs["timeout"] == LIST_REPORTS_TIMEOUT_SECONDS

    def test_report_fetch_is_bounded(self) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response({"result": {"schema": [], "rows": []}})
            source = doit_source(CONFIG, "cost_by_product", "r1", MagicMock(), None)
            list(cast(Iterable[Any], source.items()))

        assert mock_session.return_value.get.call_args.kwargs["timeout"] == REPORT_TIMEOUT_SECONDS


class TestDoitEndpointSource:
    @pytest.mark.parametrize(
        "endpoint,path,data_key,next_page",
        [
            ("Budgets", "/analytics/v1/budgets", "budgets", lambda token: {"pageToken": token}),
            ("Insights", "/insights/v1/results", "results", lambda token: {"pagination": {"pageToken": token}}),
            ("Anomalies", "/anomalies/v1", "anomalies", lambda token: {"pageToken": token}),
            ("Invoices", "/billing/v1/invoices", "invoices", lambda token: {"pageToken": token}),
            ("Assets", "/billing/v1/assets", "assets", lambda token: {"pageToken": token}),
            ("Annotations", "/analytics/v1/annotations", "annotations", lambda token: {"pageToken": token}),
            ("SupportTickets", "/support/v1/tickets", "tickets", lambda token: {"pageToken": token}),
        ],
    )
    def test_follows_the_page_token_to_the_last_page(self, endpoint, path, data_key, next_page) -> None:
        result = SourceDriver(DoItSource(), CONFIG).run(
            endpoint,
            [
                ScriptedResponse(json={data_key: [{"id": "1"}], **next_page("tok-2")}),
                ScriptedResponse(json={data_key: [{"id": "2"}]}),
            ],
        )

        assert result.raised is None
        assert result.paths == [path, path]
        assert result.params("pageToken") == [None, "tok-2"]
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert result.requests[0].headers["authorization"] == "Bearer key"

    def test_insight_resource_results_fan_out_over_every_insight(self) -> None:
        resource_results = "/insights/v1/results/source/{}/insight/{}/resource-results"
        result = SourceDriver(DoItSource(), CONFIG).run(
            "InsightResourceResults",
            [
                ScriptedResponse(
                    json={"results": [{"source": "doit", "key": "idle/vms #2"}, {"source": "aws", "key": "gone"}]}
                ),
                ScriptedResponse(json={"resourceResults": [{"resourceId": "vm-1"}], "pageToken": "tok-2"}),
                ScriptedResponse(json={"resourceResults": [{"resourceId": "vm-2"}]}),
                # An insight removed after the listing is skipped, not fatal.
                ScriptedResponse(status=404, json={"error": "not found"}),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/insights/v1/results",
            resource_results.format("doit", "idle%2Fvms%20%232"),
            resource_results.format("doit", "idle%2Fvms%20%232"),
            resource_results.format("aws", "gone"),
        ]
        assert result.params("pageToken") == [None, None, "tok-2", None]
        assert [(row["insight_source"], row["insight_key"], row["resourceId"]) for row in result.rows] == [
            ("doit", "idle/vms #2", "vm-1"),
            ("doit", "idle/vms #2", "vm-2"),
        ]

    def test_forbidden_table_fails_as_non_retryable(self) -> None:
        result = SourceDriver(DoItSource(), CONFIG).run(
            "Invoices", always(ScriptedResponse(status=403, json={"error": "forbidden"}))
        )

        assert result.raised is not None
        assert error_message_matches(str(result.raised), DoItSource().get_non_retryable_errors().keys())
