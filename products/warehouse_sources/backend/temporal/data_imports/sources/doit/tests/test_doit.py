from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit import (
    LIST_REPORTS_TIMEOUT_SECONDS,
    REPORT_TIMEOUT_SECONDS,
    doit_list_reports,
    doit_source,
    resolve_report_id,
)
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
    def test_schema_metadata_short_circuits_without_listing_reports(self) -> None:
        with patch(f"{_MODULE}.doit_list_reports") as mock_list:
            assert resolve_report_id(CONFIG, "cost_by_product", {"report_id": "r1"}) == "r1"

        mock_list.assert_not_called()

    @pytest.mark.parametrize("schema_metadata", [None, {}, {"report_id": None}])
    def test_falls_back_to_name_lookup(self, schema_metadata: dict | None) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(
                {"reports": [{"id": "r7", "reportName": "Cost by product"}]}
            )
            assert resolve_report_id(CONFIG, "cost_by_product", schema_metadata) == "r7"

    def test_raises_when_no_report_matches_the_name(self) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(
                {"reports": [{"id": "r7", "reportName": "Cost by product"}]}
            )
            with pytest.raises(Exception, match="Report no longer exists"):
                resolve_report_id(CONFIG, "deleted_report", None)


class TestDoitListReports:
    def test_returns_raw_and_normalized_names(self) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(
                {
                    "reports": [
                        {"id": "r1", "reportName": "Cost by product"},
                        {"id": "r2", "reportName": "   "},
                        {"id": "r3"},
                    ]
                }
            )
            reports = doit_list_reports(CONFIG)

        assert [(r.id, r.name, r.report_name) for r in reports] == [("r1", "cost_by_product", "Cost by product")]

    def test_non_200_surfaces_the_status_code(self) -> None:
        # `DOIT_RETRY` sets raise_on_status=False, so an exhausted 5xx lands here as a response;
        # without the guard it became a JSON/key error with the status lost.
        with patch(f"{_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response({}, status_code=500)
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
