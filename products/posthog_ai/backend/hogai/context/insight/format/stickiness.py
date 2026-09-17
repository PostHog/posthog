from typing import Any

from posthog.schema import AssistantStickinessQuery, Compare, StickinessQuery

from .utils import format_matrix, format_number


class StickinessResultsFormatter:
    """
    Compresses and formats stickiness results into a LLM-friendly string.

    Single/Multiple series:
    ```
    Interval|Series Label 1|Series Label 2
    1 day|value1|value2
    2 days|value1|value2
    ```
    """

    def __init__(
        self,
        query: AssistantStickinessQuery | StickinessQuery,
        results: list[dict[str, Any]],
    ):
        self._query = query
        self._results = results

    def format(self) -> str:
        results = self._results
        if len(results) == 0:
            return "No data recorded for this time period."

        current = []
        previous = []

        for result in results:
            if result.get("compare_label") == Compare.CURRENT or result.get("compare_label") == "current":
                current.append(result)
            elif result.get("compare_label") == Compare.PREVIOUS or result.get("compare_label") == "previous":
                previous.append(result)

        if len(previous) > 0 and len(current) > 0:
            return f"Previous period:\n{self._format_results(previous)}\n\nCurrent period:\n{self._format_results(current)}"

        return self._format_results(results)

    def _format_results(self, results: list[dict[str, Any]]) -> str:
        result = results[0]
        days = result["days"]
        labels = result["labels"]

        series_labels = []
        for series in results:
            series_labels.append(self._extract_series_label(series))

        matrix: list[list[str]] = []
        header = ["Interval", *series_labels]
        matrix.append(header)

        for i, _day in enumerate(days):
            row = [labels[i]]
            for series in results:
                row.append(format_number(series["data"][i]))
            matrix.append(row)

        return format_matrix(matrix)

    def _extract_series_label(self, series: dict[str, Any]) -> str:
        action = series.get("action")
        name = series["label"]
        if isinstance(action, dict):
            custom_name = action.get("custom_name")
            if custom_name is not None:
                name = custom_name
        return name
