from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import structlog

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


class TestCanonicalDescriptions:
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
