import re
import datetime as dt
from typing import Any

from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses import source as source_module
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

    def test_a_rejected_request_keeps_the_message_that_names_the_failing_table(self) -> None:
        # A fixed friendly string would replace the raised message and hide which of the ten
        # tables AWS rejected.
        assert self.source.get_non_retryable_errors()["Amazon SES request failed: BadRequestException"] is None

    def test_the_caption_and_the_access_denied_message_grant_the_same_iam_actions(self) -> None:
        # Both surfaces tell the user which IAM actions to grant; if they diverge, the setup
        # form and the sync error give contradictory instructions.
        caption = self.source.get_source_config.caption or ""
        denied_message = next(
            message for key, message in self.source.get_non_retryable_errors().items() if "AccessDeniedException" in key
        )
        assert denied_message is not None

        caption_actions = set(re.findall(r"ses:[A-Za-z0-9]+", caption))
        message_actions = set(re.findall(r"ses:[A-Za-z0-9]+", denied_message))
        assert caption_actions == message_actions
        assert len(caption_actions) >= 16

    def test_endpoint_permissions_pass_the_configured_credentials_through(self) -> None:
        with mock.patch.object(source_module, "probe_endpoint_permissions", return_value={"account": None}) as probe:
            assert self.source.get_endpoint_permissions(self.config, team_id=1, endpoints=["account"]) == {
                "account": None
            }

        assert probe.call_args[0] == ("AKIAEXAMPLE", "secret", None, "us-east-1", ["account"])

    def test_source_for_pipeline_forwards_the_watermark_only_on_an_incremental_run(self) -> None:
        watermark = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)

        with mock.patch.object(source_module, "aws_ses_source") as build:
            inputs = make_inputs("suppressed_destinations", True, watermark)
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)
            assert build.call_args[1]["db_incremental_field_last_value"] == watermark

            inputs = make_inputs("suppressed_destinations", False, watermark)
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)
            assert build.call_args[1]["db_incremental_field_last_value"] is None
