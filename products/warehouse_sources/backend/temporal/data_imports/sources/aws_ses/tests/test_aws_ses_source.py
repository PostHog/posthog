import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses import (
    aws_ses as transport_module,
    source as source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.source import AwsSesSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsses import AwsSesSourceConfig


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
        incremental_field="last_update_time",
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestAwsSesSource:
    def setup_method(self) -> None:
        self.source = AwsSesSource()
        self.config = AwsSesSourceConfig(
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="secret",
            aws_region="us-east-1",
            aws_session_token=None,
        )

    def test_changing_the_region_requires_reentering_the_secrets(self) -> None:
        # The region picks the host the signed request is sent to, so retargeting it must not
        # reuse a preserved secret.
        assert self.source.connection_host_fields == ["aws_region"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Amazon SES request failed: UnrecognizedClientException - The security token included in the request is invalid",
            "Amazon SES request failed: SignatureDoesNotMatch - Signature expired",
            "Amazon SES request failed: ExpiredTokenException - The security token included in the request is expired",
            "Amazon SES request failed: AccessDeniedException - not authorized to perform: ses:GetAccount",
            "Invalid AWS region: 'email.evil.example/'",
        ],
    )
    def test_permanent_aws_failures_stop_the_sync_instead_of_retrying(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Amazon SES request failed: TooManyRequestsException - Rate exceeded",
            "Amazon SES request failed: HTTP 503 - ",
        ],
    )
    def test_transient_aws_failures_keep_retrying(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_endpoint_permissions_pass_the_configured_credentials_through(self) -> None:
        with mock.patch.object(source_module, "probe_endpoint_permissions", return_value={"account": None}) as probe:
            assert self.source.get_endpoint_permissions(self.config, team_id=1, endpoints=["account"]) == {
                "account": None
            }

        assert probe.call_args[0] == ("AKIAEXAMPLE", "secret", None, "us-east-1", ["account"])

    @pytest.mark.parametrize(
        "endpoint,primary_keys",
        [
            ("account", None),
            ("configuration_sets", ["configuration_set_name"]),
            ("email_identities", ["identity_name"]),
            ("suppressed_destinations", ["email_address"]),
        ],
    )
    def test_source_for_pipeline_declares_the_endpoints_primary_key_and_a_final_commit_watermark(
        self, endpoint: str, primary_keys: list[str] | None
    ) -> None:
        inputs = make_inputs(endpoint)
        manager = self.source.get_resumable_source_manager(inputs)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        # SES documents no response ordering, so the watermark must only commit when a walk
        # completes; "asc" would checkpoint it after every batch.
        assert response.sort_mode == "desc"

    def test_source_for_pipeline_forwards_the_watermark_only_on_an_incremental_run(self) -> None:
        watermark = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)

        with mock.patch.object(source_module, "aws_ses_source") as build:
            inputs = make_inputs("suppressed_destinations", True, watermark)
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)
            assert build.call_args[1]["db_incremental_field_last_value"] == watermark

            inputs = make_inputs("suppressed_destinations", False, watermark)
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)
            assert build.call_args[1]["db_incremental_field_last_value"] is None

    def test_items_are_lazy_so_building_the_response_sends_no_request(self) -> None:
        inputs = make_inputs("suppressed_destinations")
        manager = self.source.get_resumable_source_manager(inputs)

        with mock.patch.object(transport_module, "send_request") as send:
            response = self.source.source_for_pipeline(self.config, manager, inputs)
            items = cast("Iterable[Any]", response.items())

        assert iter(items) is not None
        send.assert_not_called()
