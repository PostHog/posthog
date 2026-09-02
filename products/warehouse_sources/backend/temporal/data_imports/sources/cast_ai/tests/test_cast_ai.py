from datetime import UTC, datetime
from typing import Any, cast

from unittest.mock import Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.cast_ai import (
    CastAiResumeConfig,
    _client_config,
    _default_lookback_start,
    _format_time_value,
    _now,
    _report_incremental_config_factory,
    cast_ai_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.settings import COST_REPORT_STEP_SECONDS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


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

    def test_now_is_rfc3339(self) -> None:
        value = _now()
        assert value.endswith("Z")
        # Round-trips as RFC 3339 without raising.
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")

    def test_default_lookback_start_is_before_now(self) -> None:
        start = datetime.strptime(_default_lookback_start(), "%Y-%m-%dT%H:%M:%SZ")
        now = datetime.strptime(_now(), "%Y-%m-%dT%H:%M:%SZ")
        assert start < now


class TestCastAiIncrementalConfigFactory:
    def test_produces_start_and_end_params(self) -> None:
        factory = _report_incremental_config_factory("startTime", "endTime")
        config = factory("timestamp")

        assert config["cursor_path"] == "timestamp"
        assert config["start_param"] == "startTime"
        assert config["end_param"] == "endTime"
        assert config["convert"] is _format_time_value
        # initial_value/end_value are RFC 3339 strings usable as literal query params.
        datetime.strptime(cast(str, config["initial_value"]), "%Y-%m-%dT%H:%M:%SZ")
        datetime.strptime(cast(str, config["end_value"]), "%Y-%m-%dT%H:%M:%SZ")

    def test_end_value_is_stable_across_calls(self) -> None:
        # Both report endpoints must request the same "now" snapshot within one sync, so the
        # value is captured once at factory-creation time, not per field.
        factory = _report_incremental_config_factory("fromDate", "toDate")
        assert factory("createdAt")["end_value"] == factory("timestamp")["end_value"]


class TestCastAiGetResource:
    def test_clusters_full_refresh(self) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint="clusters"))
        assert resource["name"] == "clusters"
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/v1/kubernetes/external-clusters"
        assert resource["endpoint"]["data_selector"] == "items"
        assert isinstance(resource["endpoint"]["paginator"], SinglePagePaginator)
        assert resource["table_format"] == "delta"

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
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.cast_ai.make_tracked_session")
    def test_validate_credentials_status_mapping(self, status, expected_valid, expected_message, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status)

        result = validate_credentials(api_key="key")

        assert result == (expected_valid, expected_message)
        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.cast.ai/v1/kubernetes/external-clusters"
        assert call.kwargs["headers"]["X-API-Key"] == "key"
        # The X-API-Key header survives cross-origin redirects, so the probe must not follow them.
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    def test_client_config_disables_redirects(self) -> None:
        # Same guard for the sync path: RESTClient reads allow_redirects from the client config.
        assert _client_config(api_key="key")["allow_redirects"] is False


class TestCastAiSourceTopLevel:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.cast_ai.rest_api_resource")
    def test_top_level_response(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        response = cast_ai_source(
            api_key="key",
            endpoint="clusters",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        assert response.name == "clusters"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.cast_ai.rest_api_resource")
    def test_resumes_from_saved_state(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_manager(CastAiResumeConfig(paginator_state={"offset": 5}))

        cast_ai_source(
            api_key="key",
            endpoint="clusters",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        kwargs = mock_rest_api_resource.call_args.kwargs
        assert kwargs["initial_paginator_state"] == {"offset": 5}

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
        manager.save_state.assert_called_once_with(CastAiResumeConfig(paginator_state={"offset": 1}))

        manager.save_state.reset_mock()
        resume_hook(None)
        manager.save_state.assert_not_called()


class TestCastAiFanoutRowFormat:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_cluster_cost_reports_row_format(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("clusters", [{"id": "cluster-1"}]),
            _FakeDltResource(
                "cluster_cost_reports",
                [{"timestamp": "2026-03-01T00:00:00Z", "costOnDemand": "1.5", "_clusters_id": "cluster-1"}],
            ),
        ]

        response = cast_ai_source(
            api_key="key",
            endpoint="cluster_cost_reports",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        rows = list(cast(Any, response.items()))
        assert rows == [{"timestamp": "2026-03-01T00:00:00Z", "costOnDemand": "1.5", "cluster_id": "cluster-1"}]
        assert response.primary_keys == ["cluster_id", "timestamp"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["timestamp"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_cluster_savings_history_row_format(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("clusters", [{"id": "cluster-9"}]),
            _FakeDltResource(
                "cluster_savings_history",
                [{"createdAt": "2026-03-01T00:00:00Z", "current": {"cost": "9"}, "_clusters_id": "cluster-9"}],
            ),
        ]

        response = cast_ai_source(
            api_key="key",
            endpoint="cluster_savings_history",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        rows = list(cast(Any, response.items()))
        assert rows == [{"createdAt": "2026-03-01T00:00:00Z", "current": {"cost": "9"}, "cluster_id": "cluster-9"}]
        assert response.primary_keys == ["cluster_id", "createdAt"]


class TestCastAiFanoutWiring:
    @parameterized.expand(
        [
            ("cluster_cost_reports", "startTime", "endTime", True),
            ("cluster_savings_history", "fromDate", "toDate", False),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.cast_ai.build_dependent_resource")
    def test_fanout_wiring_per_endpoint(
        self, endpoint, start_param, end_param, expects_step_seconds, mock_build_dependent_resource
    ) -> None:
        mock_build_dependent_resource.return_value = iter([])
        manager = _make_manager(CastAiResumeConfig(paginator_state={"completed": []}))

        cast_ai_source(
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] is None
        assert isinstance(kwargs["parent_endpoint_extra"]["paginator"], SinglePagePaginator)
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], SinglePagePaginator)
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "items"
        assert kwargs["child_endpoint_extra"]["data_selector"] == "items"
        assert start_param in kwargs["child_params_extra"]
        assert end_param in kwargs["child_params_extra"]
        assert ("stepSeconds" in kwargs["child_params_extra"]) is expects_step_seconds
        if expects_step_seconds:
            assert kwargs["child_params_extra"]["stepSeconds"] == COST_REPORT_STEP_SECONDS
        assert kwargs["resume_hook"] is not None
        assert kwargs["initial_paginator_state"] == {"completed": []}

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
