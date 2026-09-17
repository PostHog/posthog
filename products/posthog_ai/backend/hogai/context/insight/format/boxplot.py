from typing import Any

from .utils import format_matrix, format_number


class BoxPlotResultsFormatter:
    """
    Compresses and formats box plot results into a LLM-friendly string.

    Single series:
    ```
    Date|Min|P25|Median|P75|Max|Mean
    2025-01-20|1.2|5.5|12.3|25.8|100.4|18.7
    ```

    Multiple series:
    ```
    Date|Series|Min|P25|Median|P75|Max|Mean
    2025-01-20|$pageview|1.2|5.5|12.3|25.8|100.4|18.7
    ```
    """

    STATS: list[tuple[str, str]] = [
        ("Min", "min"),
        ("P25", "p25"),
        ("Median", "median"),
        ("P75", "p75"),
        ("Max", "max"),
        ("Mean", "mean"),
    ]

    def __init__(self, boxplot_data: list[dict[str, Any]]):
        self._data = boxplot_data

    def format(self) -> str:
        if not self._data:
            return "No data recorded for this time period."

        series_labels = {datum.get("series_label") for datum in self._data if datum.get("series_label") is not None}
        multi_series = len(series_labels) > 1

        stat_columns = [col for col, _key in self.STATS]

        matrix: list[list[str]] = []
        if multi_series:
            matrix.append(["Date", "Series", *stat_columns])
        else:
            matrix.append(["Date", *stat_columns])

        for datum in self._data:
            row = [datum["day"]]
            if multi_series:
                row.append(datum.get("series_label") or datum.get("label", ""))
            for _col, key in self.STATS:
                row.append(format_number(datum.get(key)))
            matrix.append(row)

        return format_matrix(matrix)
