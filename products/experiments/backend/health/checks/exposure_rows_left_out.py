"""
Rows of a warehouse-native exposure query that the exposures leave out. Pure functions, no I/O.

The exposure query counts a row only with a non-empty entity_id and a variant that is one of the experiment's variants.
A second statement counts the other rows by reason, and this check puts those counts into words, so a total that looks
wrong comes with the rows behind it. The counts are the only input: the check never reads a row of the customer's
warehouse, so no entity_id reaches the finding.
"""

from posthog.schema import ExperimentWarehouseNativeRowsLeftOut

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.checks.events_received import quoted
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import (
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    CheckValues,
    not_applicable,
    not_checked,
)

# pinned: the finding's subcodes. The page sends them as `finding_subcode` on the health finding events.
UNKNOWN_VARIANT = "unknown_variant"
EMPTY_ID = "empty_id"

ONLY_ON_WAREHOUSE_NATIVE_EXPOSURES = "Runs only when the exposures come from a warehouse-native query"
COUNT_FAILED = "Couldn't check because the count of the rows left out failed"
# The variant values that the finding names. The statement returns at most 50, by row count.
SHOWN_VALUES = 5


def exposure_rows_left_out_values(ctx: HealthContext) -> CheckValues:
    left_out = _left_out(ctx)
    if left_out is None:
        return {}
    unknown = _unknown_variant_rows(left_out)
    empty = left_out.empty_id or 0
    return {
        ExperimentHealthValueKey.LEFT_OUT_ROW_COUNT: unknown + empty,
        ExperimentHealthValueKey.UNKNOWN_VARIANT_ROW_COUNT: unknown,
        ExperimentHealthValueKey.EMPTY_ID_ROW_COUNT: empty,
    }


def exposure_rows_left_out(ctx: HealthContext) -> CheckOutcome:
    if not ctx.warehouse_native_exposures:
        return not_applicable(ONLY_ON_WAREHOUSE_NATIVE_EXPOSURES)
    if not ctx.is_launched or ctx.exposures is None:
        return not_applicable(RUNS_AFTER_LAUNCH)
    left_out = ctx.exposures.rows_left_out
    if left_out is None:
        return not_checked(COUNT_FAILED)
    unknown = _unknown_variant_rows(left_out)
    empty = left_out.empty_id or 0
    if unknown + empty == 0:
        return None
    sentences: list[str] = []
    evidence: dict[str, str | int | float | bool | None] = {"unknown_variant_rows": unknown, "empty_id_rows": empty}
    if unknown:
        sentences.append(_unknown_variant_detail(left_out.unknown_variants or {}, unknown, ctx))
        for number, (value, count) in enumerate(_by_rows(left_out.unknown_variants or {})[:SHOWN_VALUES], start=1):
            evidence[f"unknown_variant_{number}"] = value
            evidence[f"unknown_variant_{number}_rows"] = count
    if empty:
        sentences.append(
            f"{_rows(empty)} of the exposure query {_have(empty)} an empty entity_id, so {_they(empty)} {_do(empty)}n't count. "
            "Check the column or the join that fills entity_id."
        )
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.EXPOSURE_ROWS_LEFT_OUT,
        subcode=UNKNOWN_VARIANT if unknown else EMPTY_ID,
        # A variant that none of the experiment's variants match is a mismatch between the query and the flag. An empty
        # id can be a row the customer's data carries on purpose, such as a visit without a customer.
        severity=ExperimentHealthFindingSeverity.WARNING if unknown else ExperimentHealthFindingSeverity.INFO,
        title=f"{_rows(unknown + empty)} of the exposure query {_do(unknown + empty)}n't count",
        detail=" ".join(sentences),
        evidence=evidence,
        actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
        diagnostic_ref=None,
    )


def _left_out(ctx: HealthContext) -> ExperimentWarehouseNativeRowsLeftOut | None:
    if not ctx.warehouse_native_exposures or ctx.exposures is None:
        return None
    return ctx.exposures.rows_left_out


def _unknown_variant_rows(left_out: ExperimentWarehouseNativeRowsLeftOut) -> int:
    # The values are capped, so their sum is a lower bound. The total is exact when the statement reported it.
    if left_out.unknown_variant_rows is not None:
        return left_out.unknown_variant_rows
    return sum((left_out.unknown_variants or {}).values())


def _by_rows(unknown_variants: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(unknown_variants.items(), key=lambda item: (-item[1], item[0]))


def _unknown_variant_detail(unknown_variants: dict[str, int], unknown: int, ctx: HealthContext) -> str:
    shown = _by_rows(unknown_variants)[:SHOWN_VALUES]
    named = ", ".join(f'"{value}" ({_rows(count)})' for value, count in shown)
    # The statement caps the values it returns, so the rows it didn't name are counted, not listed.
    more = unknown - sum(count for _, count in shown)
    if more > 0:
        named += f" and {_rows(more)} with other values"
    keys = [variant.key for variant in ctx.flag.variants if variant.key] if ctx.flag is not None else []
    variants = f" ({quoted(keys)})" if keys else ""
    return (
        f"{_rows(unknown)} of the exposure query {_have(unknown)} a variant that is none of the experiment's "
        f"variants{variants}, so {_they(unknown)} {_do(unknown)}n't count: {named}. PostHog compares the variant as text with the "
        'keys of the feature flag\'s variants, so "Control" doesn\'t match "control". Change the query so that its '
        "variant column returns those keys, or leave out the rows that aren't part of the experiment."
    )


def _rows(count: int) -> str:
    return f"{count:,} row" if count == 1 else f"{count:,} rows"


def _have(count: int) -> str:
    return "has" if count == 1 else "have"


def _they(count: int) -> str:
    return "it" if count == 1 else "they"


def _do(count: int) -> str:
    return "does" if count == 1 else "do"
