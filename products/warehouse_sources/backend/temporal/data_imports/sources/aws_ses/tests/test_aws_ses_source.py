from collections.abc import Iterable
from typing import Any, cast

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

    def test_endpoint_permissions_pass_the_configured_credentials_through(self) -> None:
        with mock.patch.object(source_module, "probe_endpoint_permissions", return_value={"account": None}) as probe:
            assert self.source.get_endpoint_permissions(self.config, team_id=1, endpoints=["account"]) == {
                "account": None
            }

        assert probe.call_args[0] == ("AKIAEXAMPLE", "secret", None, "us-east-1", ["account"])

    def test_items_are_lazy_so_building_the_response_sends_no_request(self) -> None:
        inputs = make_inputs("suppressed_destinations")
        manager = self.source.get_resumable_source_manager(inputs)

        with mock.patch.object(transport_module, "send_request") as send:
            response = self.source.source_for_pipeline(self.config, manager, inputs)
            items = cast("Iterable[Any]", response.items())

        assert iter(items) is not None
        send.assert_not_called()
