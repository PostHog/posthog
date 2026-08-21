from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets import (
    aws_budgets as transport_module,
    source as source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets.source import AwsBudgetsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsbudgets import (
    AwsBudgetsSourceConfig,
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
        incremental_field="period_start",
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestAwsBudgetsSource:
    def setup_method(self) -> None:
        self.source = AwsBudgetsSource()
        self.config = AwsBudgetsSourceConfig(
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="secret",
            aws_session_token=None,
        )

    def test_endpoint_permissions_are_probed_for_the_requested_endpoints(self) -> None:
        with mock.patch.object(source_module, "probe_endpoint_permissions", return_value={"budgets": None}) as probe:
            assert self.source.get_endpoint_permissions(self.config, team_id=1, endpoints=["budgets"]) == {
                "budgets": None
            }

        assert probe.call_args[0][3] == ["budgets"]

    @pytest.mark.parametrize(
        "should_use_incremental_field,expected_watermark",
        [(True, "2024-05-20"), (False, None)],
    )
    def test_the_watermark_only_reaches_the_transport_on_an_incremental_sync(
        self, should_use_incremental_field: bool, expected_watermark: Any
    ) -> None:
        inputs = make_inputs(
            "budget_performance_history",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value="2024-05-20",
        )
        response = self.source.source_for_pipeline(
            self.config, self.source.get_resumable_source_manager(inputs), inputs
        )

        with mock.patch.object(transport_module, "get_rows", return_value=iter([])) as get_rows:
            list(cast("Iterable[Any]", response.items()))

        assert get_rows.call_args[1]["should_use_incremental_field"] is should_use_incremental_field
        assert get_rows.call_args[1]["db_incremental_field_last_value"] == expected_watermark
        assert get_rows.call_args[1]["endpoint"] == "budget_performance_history"

    def test_credential_failures_are_reported_instead_of_retried_forever(self) -> None:
        errors = self.source.get_non_retryable_errors()

        assert all(message for message in errors.values())
        # Each key has to be a prefix of a message the transport actually raises, or the mapping
        # silently never matches.
        for key in errors:
            assert key.startswith(("AWS Budgets request failed: ", "AWS STS request failed: ", "AWS access key ID"))
