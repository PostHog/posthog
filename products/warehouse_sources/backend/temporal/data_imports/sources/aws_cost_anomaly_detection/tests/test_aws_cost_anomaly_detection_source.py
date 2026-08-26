import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_anomaly_detection import (
    aws_cost_anomaly_detection as transport_module,
    source as source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_anomaly_detection.settings import (
    AWS_COST_ANOMALY_DETECTION_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_anomaly_detection.source import (
    AwsCostAnomalyDetectionSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awscostanomalydetection import (
    AwsCostAnomalyDetectionSourceConfig,
)


def make_inputs(
    schema_name: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="anomaly_end_date",
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestAwsCostAnomalyDetectionSource:
    def setup_method(self) -> None:
        self.source = AwsCostAnomalyDetectionSource()
        self.config = AwsCostAnomalyDetectionSourceConfig(
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="secret",
            aws_session_token=None,
        )

    def test_the_form_asks_only_for_iam_credentials(self) -> None:
        # Cost Anomaly Detection is global and always signed for us-east-1, so a region field
        # would suggest a routing choice the user does not have.
        assert [field.name for field in self.source.get_source_config.fields] == [
            "aws_access_key_id",
            "aws_secret_access_key",
            "aws_session_token",
        ]

    def test_only_the_anomalies_table_syncs_incrementally(self) -> None:
        # GetAnomalies is the one operation with a server-side date filter; monitors and
        # subscriptions have no filter, so an "incremental" sync there would cost the same as a
        # full refresh.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, team_id=1)}

        assert list(schemas) == list(ENDPOINTS)
        assert schemas["anomalies"].supports_incremental is True
        assert [field["field"] for field in schemas["anomalies"].incremental_fields] == ["anomaly_end_date"]
        assert schemas["anomaly_monitors"].supports_incremental is False
        assert schemas["anomaly_subscriptions"].supports_incremental is False
        assert all(schema.description for schema in schemas.values())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "AWS Cost Anomaly Detection request failed: AccessDeniedException - User is not authorized to perform ce:GetAnomalies",
            "AWS Cost Anomaly Detection request failed: UnrecognizedClientException - The security token included in the request is invalid",
            "AWS Cost Anomaly Detection request failed: ExpiredTokenException - The security token included in the request is expired",
            "AWS Cost Anomaly Detection request failed: SignatureDoesNotMatch - Signature expired",
            "AWS Cost Anomaly Detection request failed: DataUnavailableException - no data",
        ],
    )
    def test_permanent_aws_failures_stop_the_sync_instead_of_retrying(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "AWS Cost Anomaly Detection request failed: LimitExceededException - Rate exceeded",
            "AWS Cost Anomaly Detection request failed: HTTP 503 - ",
        ],
    )
    def test_transient_aws_failures_keep_retrying(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_endpoint_permissions_are_probed_per_table_for_the_schema_picker(self) -> None:
        with mock.patch.object(source_module, "probe_endpoint_permissions", return_value={"anomalies": None}) as probe:
            assert self.source.get_endpoint_permissions(self.config, 1, ["anomalies"]) == {"anomalies": None}

        assert probe.call_args[0] == ("AKIAEXAMPLE", "secret", None, ["anomalies"])

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_carries_the_endpoints_primary_key(self, endpoint: str) -> None:
        inputs = make_inputs(endpoint)
        manager = self.source.get_resumable_source_manager(inputs)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == endpoint
        assert response.primary_keys == AWS_COST_ANOMALY_DETECTION_ENDPOINTS[endpoint].primary_key
        # AWS documents no ordering for these operations, so the watermark only commits once the
        # walk has finished.
        assert response.sort_mode == "desc"

    def test_anomalies_partition_on_the_start_date_because_it_never_moves(self) -> None:
        # The end date keeps moving while an anomaly is open, so partitioning on it would rewrite
        # partitions every sync.
        inputs = make_inputs("anomalies")

        response = self.source.source_for_pipeline(
            self.config, self.source.get_resumable_source_manager(inputs), inputs
        )

        assert response.partition_keys == ["anomaly_start_date"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"

    @pytest.mark.parametrize("endpoint", ["anomaly_monitors", "anomaly_subscriptions"])
    def test_the_dateless_tables_are_not_partitioned(self, endpoint: str) -> None:
        inputs = make_inputs(endpoint)

        response = self.source.source_for_pipeline(
            self.config, self.source.get_resumable_source_manager(inputs), inputs
        )

        assert response.partition_keys is None
        assert response.partition_mode is None

    def test_source_for_pipeline_forwards_the_watermark_only_on_an_incremental_run(self) -> None:
        watermark = dt.datetime(2024, 5, 1, tzinfo=dt.UTC)

        with mock.patch.object(source_module, "aws_cost_anomaly_detection_source") as build:
            inputs = make_inputs("anomalies", True, watermark)
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)
            assert build.call_args[1]["db_incremental_field_last_value"] == watermark

            inputs = make_inputs("anomalies", False, watermark)
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)
            assert build.call_args[1]["db_incremental_field_last_value"] is None

    def test_items_are_lazy_so_building_the_response_bills_no_api_request(self) -> None:
        inputs = make_inputs("anomalies")
        manager = self.source.get_resumable_source_manager(inputs)

        with mock.patch.object(transport_module, "send_operation") as send:
            response = self.source.source_for_pipeline(self.config, manager, inputs)
            items = cast("Iterable[Any]", response.items())

        assert iter(items) is not None
        send.assert_not_called()
