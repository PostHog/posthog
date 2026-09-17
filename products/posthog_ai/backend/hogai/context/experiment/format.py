from typing import Any

NO_DATA_MARKER = "—"


def _safe_mean(sum_value: Any, number_of_samples: Any) -> float | None:
    if sum_value is None or not number_of_samples:
        return None
    try:
        return float(sum_value) / float(number_of_samples)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _format_number(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num.is_integer() and abs(num) < 1e15:
        return str(int(num))
    formatted = f"{num:.5g}"
    return formatted


def _format_bool(value: Any) -> str:
    if value is None:
        return "N/A"
    return "true" if bool(value) else "false"


def _format_interval(interval: Any) -> str:
    if not interval or len(interval) < 2:
        return "N/A"
    low, high = interval[0], interval[1]
    return f"{_format_number(low)}..{_format_number(high)}"


def _detect_method(variant_results: list[dict]) -> str | None:
    for variant in variant_results:
        method = variant.get("method")
        if method:
            return str(method)
    return None


def _variant_key_order(variant_results: list[dict]) -> list[str]:
    keys: list[str] = []
    for variant in variant_results:
        key = variant.get("key")
        if isinstance(key, str) and key not in keys:
            keys.append(key)
    return keys


class ExperimentTimeseriesFormatter:
    """
    Compresses experiment timeseries results into LLM-friendly text.

    Output is a pipe-delimited matrix with one row per day and per-variant scalar stats
    (mean = sum/n, plus interval and significance signal). Days without data are emitted
    as a single ``—`` marker. The header lists the statistical method and variant order
    so the rest of the table is unambiguous.
    """

    def __init__(self, response: dict[str, Any]):
        self._response = response

    def format(self) -> str:
        timeseries = self._response.get("timeseries") or {}
        if not timeseries:
            return "No timeseries data."

        sample_response = self._first_non_null_response(timeseries)
        if sample_response is None:
            return self._format_empty()

        variant_results = sample_response.get("variant_results") or []
        method = _detect_method(variant_results) or "unknown"
        variant_keys = _variant_key_order(variant_results)

        header_lines = [
            f"Method: {method}",
            f"Variants: control (baseline), {', '.join(variant_keys) if variant_keys else 'none'}",
        ]
        status = self._response.get("status")
        if status:
            header_lines.append(f"Status: {status}")

        header_row = ["Date", "control n", "control mean"]
        for key in variant_keys:
            header_row.extend([f"{key} n", f"{key} mean", f"{key} interval", self._effect_label(method, key)])
            header_row.append(f"{key} significant")

        matrix: list[list[str]] = [header_row]
        for date_key in sorted(timeseries.keys()):
            day_response = timeseries[date_key]
            if not day_response:
                matrix.append([date_key, NO_DATA_MARKER])
                continue
            matrix.append(self._row_for_day(date_key, day_response, variant_keys, method))

        body = "\n".join("|".join(row) for row in matrix)
        return "\n".join(header_lines) + "\n" + body

    def _first_non_null_response(self, timeseries: dict[str, Any]) -> dict[str, Any] | None:
        for value in timeseries.values():
            if isinstance(value, dict):
                return value
        return None

    def _format_empty(self) -> str:
        status = self._response.get("status") or "pending"
        return f"No completed timeseries data (status: {status})."

    def _effect_label(self, method: str, variant_key: str) -> str:
        if method == "bayesian":
            return f"{variant_key} chance_to_win"
        if method == "frequentist":
            return f"{variant_key} p_value"
        return f"{variant_key} effect"

    def _row_for_day(
        self,
        date_key: str,
        day_response: dict[str, Any],
        variant_keys: list[str],
        method: str,
    ) -> list[str]:
        baseline = day_response.get("baseline") or {}
        baseline_n = baseline.get("number_of_samples")
        baseline_mean = _safe_mean(baseline.get("sum"), baseline_n)

        row = [date_key, _format_number(baseline_n), _format_number(baseline_mean)]

        variants_by_key: dict[str, dict[str, Any]] = {}
        for variant in day_response.get("variant_results") or []:
            key = variant.get("key")
            if isinstance(key, str):
                variants_by_key[key] = variant

        for key in variant_keys:
            variant = variants_by_key.get(key) or {}
            n = variant.get("number_of_samples")
            mean = _safe_mean(variant.get("sum"), n)
            interval = variant.get("credible_interval") or variant.get("confidence_interval")
            effect = variant.get("chance_to_win") if method == "bayesian" else variant.get("p_value")
            row.extend(
                [
                    _format_number(n),
                    _format_number(mean),
                    _format_interval(interval),
                    _format_number(effect),
                    _format_bool(variant.get("significant")),
                ]
            )

        return row
