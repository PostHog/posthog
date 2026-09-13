from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import structlog

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets import (
    aws_budgets as transport_module,
    source as source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets.aws_budgets import (
    BudgetRef,
    normalize_budget,
    normalize_history_rows,
    normalize_notification_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets.settings import (
    AWS_BUDGETS_ENDPOINTS,
    ENDPOINTS,
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

    def test_the_credential_form_asks_only_for_an_iam_key(self) -> None:
        # Budgets is global, so there is no region to route on and none to ask for.
        fields = [cast(SourceFieldInputConfig, field) for field in self.source.get_source_config.fields]

        assert [field.name for field in fields] == [
            "aws_access_key_id",
            "aws_secret_access_key",
            "aws_session_token",
        ]
        assert [field.required for field in fields] == [True, True, False]
        secret_fields = [field.name for field in fields if field.type == SourceFieldInputConfigType.PASSWORD]
        assert secret_fields == ["aws_secret_access_key", "aws_session_token"]

    def test_only_the_history_table_syncs_incrementally(self) -> None:
        # Budgets and notifications have no server-side time filter, so an "incremental" sync of
        # them would still read everything.
        by_name = {schema.name: schema for schema in self.source.get_schemas(self.config, team_id=1)}

        assert by_name["budget_performance_history"].supports_incremental is True
        assert [f["field"] for f in by_name["budget_performance_history"].incremental_fields] == ["period_start"]
        assert by_name["budgets"].supports_incremental is False
        assert by_name["notifications"].supports_incremental is False

    def test_endpoint_permissions_are_probed_for_the_requested_endpoints(self) -> None:
        with mock.patch.object(source_module, "probe_endpoint_permissions", return_value={"budgets": None}) as probe:
            assert self.source.get_endpoint_permissions(self.config, team_id=1, endpoints=["budgets"]) == {
                "budgets": None
            }

        assert probe.call_args[0][3] == ["budgets"]

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_declares_the_endpoints_primary_key(self, endpoint: str) -> None:
        response = self.source.source_for_pipeline(
            self.config, self.source.get_resumable_source_manager(make_inputs(endpoint)), make_inputs(endpoint)
        )

        assert response.name == endpoint
        assert response.primary_keys == AWS_BUDGETS_ENDPOINTS[endpoint].primary_key
        # AWS documents no ordering for these operations, so the watermark may only commit at the
        # end of a completed walk.
        assert response.sort_mode == "desc"

    def test_only_the_history_table_is_partitioned_by_period(self) -> None:
        history = self.source.source_for_pipeline(
            self.config,
            self.source.get_resumable_source_manager(make_inputs("budget_performance_history")),
            make_inputs("budget_performance_history"),
        )
        budgets = self.source.source_for_pipeline(
            self.config,
            self.source.get_resumable_source_manager(make_inputs("budgets")),
            make_inputs("budgets"),
        )

        assert history.partition_keys == ["period_start"]
        assert history.partition_mode == "datetime"
        assert history.partition_format == "month"
        assert budgets.partition_keys is None
        assert budgets.partition_mode is None

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


class TestCanonicalDescriptions:
    def test_every_documented_table_is_a_table_the_source_syncs(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS) <= set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint,columns",
        [
            (
                "budgets",
                set(
                    normalize_budget(
                        {
                            "BudgetName": "b",
                            "BudgetLimit": {},
                            "CalculatedSpend": {"ActualSpend": {}, "ForecastedSpend": {}},
                            "TimePeriod": {},
                            "AutoAdjustData": {"HistoricalOptions": {}},
                            "HealthStatus": {},
                            "CostTypes": {},
                        }
                    )
                ),
            ),
            (
                "budget_performance_history",
                set(
                    normalize_history_rows(
                        BudgetRef(name="b", time_unit="MONTHLY"),
                        {
                            "BudgetPerformanceHistory": {
                                "BudgetedAndActualAmountsList": [
                                    {"BudgetedAmount": {}, "ActualAmount": {}, "TimePeriod": {}}
                                ]
                            }
                        },
                    )[0]
                ),
            ),
            (
                "notifications",
                set(normalize_notification_rows(BudgetRef(name="b", time_unit="MONTHLY"), {"Notifications": [{}]})[0]),
            ),
        ],
    )
    def test_documented_columns_match_the_columns_the_source_emits(self, endpoint: str, columns: set[str]) -> None:
        # A renamed column would otherwise leave a description attached to a column that no longer
        # exists, and the real one silently undocumented.
        documented = set(CANONICAL_DESCRIPTIONS[endpoint].get("columns") or {})

        assert documented == columns
