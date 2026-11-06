from products.experiments.backend.logic.result_stats import (
    Interval,
    MetricResultStats,
    MetricTimeseries,
    StatsMethod,
    VariantStats,
)

NO_DATA_MARKER = "—"


def _format_number(value: float | None) -> str:
    if value is None:
        return "N/A"
    num = float(value)
    if num.is_integer() and abs(num) < 1e15:
        return str(int(num))
    return f"{num:.5g}"


def _format_bool(value: bool | None) -> str:
    if value is None:
        return "N/A"
    return "true" if value else "false"


def _format_interval(interval: Interval | None) -> str:
    if interval is None:
        return "N/A"
    return f"{_format_number(interval.low)}..{_format_number(interval.high)}"


class ExperimentTimeseriesFormatter:
    """
    Compresses experiment timeseries results into LLM-friendly text.

    Output is a pipe-delimited matrix with one row per day and per-variant scalar stats
    (mean = sum/n, plus interval and significance signal). Days without data are emitted
    as a single ``—`` marker. The header lists the statistical method and variant order
    so the rest of the table is unambiguous.
    """

    def __init__(self, timeseries: MetricTimeseries):
        self._timeseries = timeseries

    def format(self) -> str:
        if not self._timeseries.days:
            return "No timeseries data."

        reference = self._timeseries.first_result
        if reference is None:
            return f"No completed timeseries data (status: {self._timeseries.status})."

        method = reference.method
        baseline_key = reference.baseline.key
        variant_keys = list(dict.fromkeys(variant.key for variant in reference.variants))

        header_lines = [
            f"Method: {method or 'unknown'}",
            f"Variants: {baseline_key} (baseline), {', '.join(variant_keys) if variant_keys else 'none'}",
            f"Status: {self._timeseries.status}",
        ]

        header_row = ["Date", f"{baseline_key} n", f"{baseline_key} mean"]
        for key in variant_keys:
            header_row.extend([f"{key} n", f"{key} mean", f"{key} interval", self._effect_label(method, key)])
            header_row.append(f"{key} significant")

        matrix: list[list[str]] = [header_row]
        for day in self._timeseries.days:
            if day.result is None:
                matrix.append([day.date, NO_DATA_MARKER])
                continue
            matrix.append(self._row_for_day(day.date, day.result, variant_keys, method))

        body = "\n".join("|".join(row) for row in matrix)
        return "\n".join(header_lines) + "\n" + body

    def _effect_label(self, method: StatsMethod | None, variant_key: str) -> str:
        match method:
            case "bayesian":
                return f"{variant_key} chance_to_win"
            case "frequentist":
                return f"{variant_key} p_value"
            case None:
                return f"{variant_key} effect"

    def _row_for_day(
        self,
        date: str,
        result: MetricResultStats,
        variant_keys: list[str],
        method: StatsMethod | None,
    ) -> list[str]:
        row = [date, _format_number(result.baseline.number_of_samples), _format_number(result.baseline.mean)]
        for key in variant_keys:
            row.extend(self._variant_cells(result.variant(key), method))
        return row

    def _variant_cells(self, variant: VariantStats | None, method: StatsMethod | None) -> list[str]:
        if variant is None:
            return ["N/A"] * 5
        # The method comes from the first day with data. A day stored with the other method
        # has no value for this column, so its cell renders as N/A.
        effect = variant.chance_to_win if method == "bayesian" else variant.p_value
        return [
            _format_number(variant.number_of_samples),
            _format_number(variant.mean),
            _format_interval(variant.interval),
            _format_number(effect),
            _format_bool(variant.significant),
        ]
