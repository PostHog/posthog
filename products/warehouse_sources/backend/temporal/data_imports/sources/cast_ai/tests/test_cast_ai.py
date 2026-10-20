from datetime import UTC, datetime

from unittest.mock import Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.cast_ai import (
    CastAiResumeConfig,
    _client_config,
    _format_time_value,
    _report_incremental_config_factory,
    cast_ai_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.settings import (
    COST_REPORT_STEP_SECONDS,
    WORKLOAD_PRIMARY_KEY,
    WORKLOAD_REPORT_STEP_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.source import CastAiSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.castai import CastAiSourceConfig


def _make_manager(resume_state: CastAiResumeConfig | None = None) -> Mock:
    manager = Mock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class TestCastAiDateFormatting:
    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45, 999999), "2026-03-01T12:30:45Z"),
            ("aware_datetime", datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC), "2026-03-01T12:30:45Z"),
            ("passthrough_string", "1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z"),
        ]
    )
    def test_format_time_value(self, _name, value, expected) -> None:
        assert _format_time_value(value) == expected


class TestCastAiIncrementalConfigFactory:
    def test_produces_start_and_end_params(self) -> None:
        factory = _report_incremental_config_factory(
            "startTime", "endTime", "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z"
        )
        config = factory("timestamp")

        assert config["cursor_path"] == "timestamp"
        assert config["start_param"] == "startTime"
        assert config["end_param"] == "endTime"
        assert config["initial_value"] == "2026-02-01T00:00:00Z"
        assert config["end_value"] == "2026-03-01T00:00:00Z"
        assert config["convert"] is _format_time_value


class TestCastAiGetResource:
    def test_rejects_fanout_endpoint(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(endpoint="cluster_cost_reports")


class TestCastAiValidateCredentials:
    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid or unauthorized CAST AI API key"),
            (403, False, "Invalid or unauthorized CAST AI API key"),
            (500, False, "CAST AI API returned an unexpected status: 500"),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        script = always(ScriptedResponse(status=status)) if status == 500 else [ScriptedResponse(status=status)]
        with scripted_network(script) as network:
            result = validate_credentials(api_key="key")

        assert result == (expected_valid, expected_message)
        assert {request.url for request in network.requests_log} == {
            "https://api.cast.ai/v1/kubernetes/external-clusters"
        }
        assert network.requests_log[0].headers["x-api-key"] == "key"
        # The X-API-Key header survives cross-origin redirects, so the probe must not follow them.
        assert network.session_options[0]["allow_redirects"] is False

    def test_client_config_disables_redirects(self) -> None:
        # Same guard for the sync path: RESTClient reads allow_redirects from the client config.
        assert _client_config(api_key="key")["allow_redirects"] is False


class TestCastAiSourceTopLevel:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.cast_ai.rest_api_resource")
    def test_saves_checkpoints_after_batches(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_manager()

        cast_ai_source(
            api_key="key",
            endpoint="clusters",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]
        resume_hook({"offset": 1})
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].paginator_state == {"offset": 1}

        manager.save_state.reset_mock()
        resume_hook(None)
        manager.save_state.assert_not_called()


class TestCastAiFanoutRowFormat:
    def test_cluster_cost_reports_row_format(self) -> None:
        result = SourceDriver(CastAiSource(), CastAiSourceConfig(api_key="key")).run(
            "cluster_cost_reports",
            [
                ScriptedResponse(json={"items": [{"id": "cluster-1"}]}),
                ScriptedResponse(
                    json={
                        "items": [
                            {"timestamp": "2026-03-01T00:00:00Z", "costOnDemand": "1.5"},
                        ]
                    }
                ),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"timestamp": "2026-03-01T00:00:00Z", "costOnDemand": "1.5", "cluster_id": "cluster-1"}]
        assert result.response is not None
        assert result.response.primary_keys == ["cluster_id", "timestamp"]
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["timestamp"]

    def test_cluster_savings_history_row_format(self) -> None:
        result = SourceDriver(CastAiSource(), CastAiSourceConfig(api_key="key")).run(
            "cluster_savings_history",
            [
                ScriptedResponse(json={"items": [{"id": "cluster-9"}]}),
                ScriptedResponse(json={"items": [{"createdAt": "2026-03-01T00:00:00Z", "current": {"cost": "9"}}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"createdAt": "2026-03-01T00:00:00Z", "current": {"cost": "9"}, "cluster_id": "cluster-9"}
        ]
        assert result.response is not None
        assert result.response.primary_keys == ["cluster_id", "createdAt"]


class TestCastAiWorkloadPagination:
    @parameterized.expand(
        [
            ("workload_cost_reports",),
            ("workload_efficiency_reports",),
            ("workload_data_transfer_costs",),
        ]
    )
    def test_walks_cursor_pages_per_cluster(self, endpoint: str) -> None:
        workload = {"namespace": "default", "workloadType": "Deployment"}
        result = SourceDriver(CastAiSource(), CastAiSourceConfig(api_key="key")).run(
            endpoint,
            [
                ScriptedResponse(json={"items": [{"id": "cluster-1"}]}),
                ScriptedResponse(json={"items": [{**workload, "workloadName": "api"}], "nextCursor": "page-2"}),
                ScriptedResponse(json={"items": [{**workload, "workloadName": "worker"}], "nextCursor": ""}),
            ],
        )

        assert result.raised is None
        assert result.params("page.cursor") == [None, None, "page-2"]
        # The report window is required on every page, not only the first.
        assert result.requests[2].param("startTime") == result.requests[1].param("startTime") is not None
        assert result.requests[2].param("endTime") == result.requests[1].param("endTime") is not None
        # Every checkpoint carries the window its rows cover, so a resumed run requests the same one.
        assert {(state.window_start, state.window_end) for state in result.saved_states} == {
            (result.requests[1].param("startTime"), result.requests[1].param("endTime"))
        }
        assert result.rows == [
            {**workload, "workloadName": "api", "cluster_id": "cluster-1"},
            {**workload, "workloadName": "worker", "cluster_id": "cluster-1"},
        ]
        assert result.response is not None
        assert result.response.primary_keys == WORKLOAD_PRIMARY_KEY


class TestCastAiFanoutWiring:
    @parameterized.expand(
        [
            ("cluster_cost_reports", "cost", "startTime", "endTime", COST_REPORT_STEP_SECONDS),
            ("cluster_savings_history", "estimated-savings-history", "fromDate", "toDate", None),
            ("cluster_savings_reports", "savings", "startTime", "endTime", COST_REPORT_STEP_SECONDS),
            ("workload_cost_reports", "workload-costs", "startTime", "endTime", WORKLOAD_REPORT_STEP_SECONDS),
            ("workload_efficiency_reports", "workload-efficiency", "startTime", "endTime", None),
            (
                "workload_data_transfer_costs",
                "datatransfer-costs",
                "startTime",
                "endTime",
                WORKLOAD_REPORT_STEP_SECONDS,
            ),
        ]
    )
    def test_fanout_wiring_per_endpoint(
        self, endpoint: str, report: str, start_param: str, end_param: str, step_seconds: int | None
    ) -> None:
        child_path = f"/v1/cost-reports/clusters/{{cluster_id}}/{report}"
        result = SourceDriver(CastAiSource(), CastAiSourceConfig(api_key="key")).run(
            endpoint,
            [
                ScriptedResponse(json={"items": [{"id": "cluster-1"}, {"id": "cluster-2"}]}),
                ScriptedResponse(json={"items": [{"timestamp": "2026-03-01T00:00:00Z"}]}),
            ],
            resume_state=CastAiResumeConfig(
                paginator_state={"completed": [child_path.format(cluster_id="cluster-1")]},
                window_start="2026-02-01T00:00:00Z",
                window_end="2026-03-01T00:00:00Z",
            ),
        )

        assert result.raised is None
        assert result.paths == [
            "/v1/kubernetes/external-clusters",
            child_path.format(cluster_id="cluster-2"),
        ]
        assert result.params("limit") == [None, None]
        assert result.rows == [{"timestamp": "2026-03-01T00:00:00Z", "cluster_id": "cluster-2"}]
        assert result.requests[0].param(start_param) is None
        assert result.requests[0].param(end_param) is None
        assert result.requests[1].param(start_param) == "2026-02-01T00:00:00Z"
        assert result.requests[1].param(end_param) == "2026-03-01T00:00:00Z"
        assert result.requests[1].param("stepSeconds") == (str(step_seconds) if step_seconds else None)
        assert result.saved_states == [
            CastAiResumeConfig(
                paginator_state={
                    "completed": [
                        child_path.format(cluster_id="cluster-1"),
                        child_path.format(cluster_id="cluster-2"),
                    ],
                    "current": None,
                    "child_state": None,
                },
                window_start="2026-02-01T00:00:00Z",
                window_end="2026-03-01T00:00:00Z",
            )
        ]

    @parameterized.expand(
        [
            ("incremental", True, datetime(2026, 3, 1, tzinfo=UTC)),
            ("first_sync", True, None),
            ("non_incremental", False, datetime(2026, 3, 1, tzinfo=UTC)),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.cast_ai.build_dependent_resource")
    def test_passes_watermark(
        self, _name, should_use_incremental_field, last_value, mock_build_dependent_resource
    ) -> None:
        mock_build_dependent_resource.return_value = iter([])

        cast_ai_source(
            api_key="key",
            endpoint="cluster_cost_reports",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
            incremental_field="timestamp",
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is should_use_incremental_field
        assert kwargs["db_incremental_field_last_value"] == last_value
        assert kwargs["incremental_field"] == "timestamp"
