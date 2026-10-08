import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import DEFAULT_RETRY
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit import (
    DOIT_RETRY,
    DoItReport,
    doit_list_reports,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.doit.source import DoItSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.doit import DoItSourceConfig

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.doit.source"
_DOIT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit"

CONFIG = DoItSourceConfig(api_key="key")


class TestDoItSource:
    def setup_method(self):
        self.source = DoItSource()

    def test_retryable_errors_cover_the_concurrent_query_quota(self):
        error_msg = (
            'Request to get report failed with status: 429. With body: {"error":"concurrent report query '
            'requests quota for \\"some-account-id\\" exhausted; please wait for previous requests to complete."}'
        )

        # Self-recovering once the other in-flight report queries finish, so it must stay retryable
        # (and out of the non-retryable set) rather than disabling the schema.
        assert error_message_matches(error_msg, self.source.get_retryable_errors())
        assert not error_message_matches(error_msg, self.source.get_non_retryable_errors().keys())

    def test_get_schemas_stamps_the_report_id_so_renames_stay_resolvable(self):
        with patch(
            f"{_SOURCE_MODULE}.doit_list_reports",
            return_value=[DoItReport(id="r1", name="cost_by_product", report_name="Cost by product")],
        ):
            schemas = self.source.get_schemas(CONFIG, team_id=1)

        assert [(s.name, s.label, s.schema_metadata) for s in schemas] == [
            ("cost_by_product", "Cost by product", {"report_id": "r1"})
        ]

    def test_source_for_pipeline_fetches_the_report_id_from_schema_metadata(self):
        inputs = MagicMock(
            spec=SourceInputs,
            schema_name="cost_by_product",
            schema_metadata={"report_id": "r1"},
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            logger=MagicMock(),
        )

        with patch(f"{_SOURCE_MODULE}.doit_source") as mock_source:
            self.source.source_for_pipeline(CONFIG, inputs)

        assert mock_source.call_args.args[1:] == ("cost_by_product", "r1")

    @pytest.mark.parametrize("status_code", [520, 521, 522, 523, 524])
    def test_doit_retry_includes_cloudflare_transient_statuses(self, status_code):
        assert status_code in (DOIT_RETRY.status_forcelist or ())

    def test_doit_retry_preserves_default_statuses(self):
        assert set(DEFAULT_RETRY.status_forcelist or ()).issubset(set(DOIT_RETRY.status_forcelist or ()))


def _reports_response(reports: list[dict], page_token: str | None = None) -> MagicMock:
    res = MagicMock()
    res.status_code = 200
    body: dict = {"reports": reports}
    if page_token is not None:
        body["pageToken"] = page_token
    res.json.return_value = body
    return res


class TestDoItListReportsPagination:
    def test_follows_page_tokens_until_exhausted(self):
        session = MagicMock()
        session.get.side_effect = [
            _reports_response([{"id": "r1", "reportName": "First"}], page_token="tok-2"),
            _reports_response([{"id": "r2", "reportName": "Second"}]),
        ]

        with patch(f"{_DOIT_MODULE}.make_tracked_session", return_value=session):
            reports = doit_list_reports(CONFIG)

        assert [r.id for r in reports] == ["r1", "r2"]
        assert session.get.call_count == 2
        assert "pageToken=tok-2" in session.get.call_args_list[1].args[0]

    def test_stops_when_the_server_echoes_the_same_page_token(self):
        session = MagicMock()
        session.get.side_effect = [
            _reports_response([{"id": "r1", "reportName": "First"}], page_token="tok"),
            _reports_response([{"id": "r2", "reportName": "Second"}], page_token="tok"),
        ]

        with patch(f"{_DOIT_MODULE}.make_tracked_session", return_value=session):
            reports = doit_list_reports(CONFIG)

        assert [r.id for r in reports] == ["r1", "r2"]
        assert session.get.call_count == 2
