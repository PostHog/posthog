from dataclasses import replace
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from posthog.schema import ExperimentWarehouseNativeRowsLeftOut, MultipleVariantHandling

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.checks.exposure_rows_left_out import (
    COUNT_FAILED,
    EMPTY_ID,
    ONLY_ON_WAREHOUSE_NATIVE_EXPOSURES,
    UNKNOWN_VARIANT,
    exposure_rows_left_out,
    exposure_rows_left_out_values,
)
from products.experiments.backend.health.context import ExposureTotals, FlagState, HealthContext
from products.experiments.backend.health.skips import RUNS_AFTER_LAUNCH, CheckOutcome, not_applicable, not_checked
from products.experiments.backend.health.test.factories import DRAFT, RUNNING_CONTEXT
from products.feature_flags.backend.facade.edits import FlagVariant

TOTALS = ExposureTotals(
    total_exposures={"control": 503, "test": 503},
    multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
    sample_ratio_mismatch_p_value=None,
    sample_ratio_expected={},
    daily_exposures={},
    hours_since_launch=72,
    counts_groups=False,
    filters_test_accounts=False,
    has_positive_test_account_filter=False,
)
FLAG = FlagState(
    active=True,
    deleted=False,
    release_groups=(),
    variants=(FlagVariant(key="control", rollout_percentage=50), FlagVariant(key="test", rollout_percentage=50)),
    reachable_conditions=(),
)
NOTHING_LEFT_OUT = ExperimentWarehouseNativeRowsLeftOut(unknown_variants={}, empty_id=0)


def _context(left_out: ExperimentWarehouseNativeRowsLeftOut | None, **changes: Any) -> HealthContext:
    return replace(
        RUNNING_CONTEXT,
        warehouse_native_exposures=True,
        flag=FLAG,
        exposures=replace(TOTALS, rows_left_out=left_out),
        **changes,
    )


class TestExposureRowsLeftOut(TestCase):
    @parameterized.expand(
        [
            (
                "event_exposures_have_no_rows_to_leave_out",
                replace(RUNNING_CONTEXT, exposures=TOTALS),
                not_applicable(ONLY_ON_WAREHOUSE_NATIVE_EXPOSURES),
            ),
            ("a_draft_has_no_exposures_yet", _context(NOTHING_LEFT_OUT, **DRAFT), not_applicable(RUNS_AFTER_LAUNCH)),
            ("a_failed_count_is_not_checked", _context(None), not_checked(COUNT_FAILED)),
            ("nothing_left_out_passes", _context(NOTHING_LEFT_OUT), None),
        ]
    )
    def test_when_the_check_looks(self, _name: str, ctx: HealthContext, expected: CheckOutcome) -> None:
        self.assertEqual(exposure_rows_left_out(ctx), expected)

    def test_names_the_variants_that_match_nothing(self) -> None:
        # The statement names at most 50 values, so the total can be larger than the values it names.
        left_out = ExperimentWarehouseNativeRowsLeftOut(
            unknown_variants={"holdout": 1, "Control": 3}, unknown_variant_rows=6, empty_id=1
        )

        finding = exposure_rows_left_out(_context(left_out))

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            (finding.code, finding.subcode, finding.severity, finding.title, finding.actions),
            (
                ExperimentHealthFindingCode.EXPOSURE_ROWS_LEFT_OUT,
                UNKNOWN_VARIANT,
                ExperimentHealthFindingSeverity.WARNING,
                "7 rows of the exposure query don't count",
                (ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
            ),
        )
        self.assertEqual(
            finding.detail,
            "6 rows of the exposure query have a variant that is none of the experiment's variants "
            '("control" and "test"), so they don\'t count: "Control" (3 rows), "holdout" (1 row) and 2 rows with other '
            "values. PostHog compares the "
            'variant as text with the keys of the feature flag\'s variants, so "Control" doesn\'t match "control". '
            "Change the query so that its variant column returns those keys, or leave out the rows that aren't part "
            "of the experiment. 1 row of the exposure query has an empty entity_id, so it doesn't count. Check the "
            "column or the join that fills entity_id.",
        )
        self.assertEqual(
            dict(finding.evidence),
            {
                "unknown_variant_rows": 6,
                "empty_id_rows": 1,
                "unknown_variant_1": "Control",
                "unknown_variant_1_rows": 3,
                "unknown_variant_2": "holdout",
                "unknown_variant_2_rows": 1,
            },
        )

    def test_empty_ids_alone_are_information(self) -> None:
        finding = exposure_rows_left_out(_context(ExperimentWarehouseNativeRowsLeftOut(empty_id=1)))

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            (finding.subcode, finding.severity, finding.title),
            (EMPTY_ID, ExperimentHealthFindingSeverity.INFO, "1 row of the exposure query doesn't count"),
        )
        self.assertNotIn("variant", finding.detail)

    def test_reads_the_counts_by_reason(self) -> None:
        left_out = ExperimentWarehouseNativeRowsLeftOut(unknown_variants={"Control": 3, "holdout": 1}, empty_id=2)

        self.assertEqual(
            exposure_rows_left_out_values(_context(left_out)),
            {
                ExperimentHealthValueKey.LEFT_OUT_ROW_COUNT: 6,
                ExperimentHealthValueKey.UNKNOWN_VARIANT_ROW_COUNT: 4,
                ExperimentHealthValueKey.EMPTY_ID_ROW_COUNT: 2,
            },
        )
        self.assertEqual(exposure_rows_left_out_values(replace(RUNNING_CONTEXT, exposures=TOTALS)), {})
