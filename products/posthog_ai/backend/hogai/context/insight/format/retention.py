from posthog.schema import AssistantRetentionQuery, RetentionPeriod, RetentionQuery

from .utils import format_matrix, format_number, format_percentage, strip_datetime_seconds


class RetentionResultsFormatter:
    """
    Compresses and formats retention results into a LLM-friendly string.

    Example answer:
    ```
    Start Date: date
    Period: period
    Date|Number of persons on date|Day 0|Day 1|Day 2|Day 3
    2024-01-28|Total Persons on Date 1|Percentage of retained users on 2024-01-29|Percentage of retained users on 2024-01-30|Percentage of retained users on 2024-01-31
    2024-01-29|Total Persons on Date 2|Percentage of retained users on 2024-01-30|Percentage of retained users on 2024-01-31
    2024-01-30|Total Persons on Date 3|Percentage of retained users on 2024-01-31
    2024-01-31|Total Persons on Date 4
    ```
    """

    def __init__(self, query: AssistantRetentionQuery | RetentionQuery, results: list[dict]):
        self._query = query
        self._results = results

    def format(self) -> str:
        results = self._results
        period = self._period

        if not results:
            return "No data recorded for this time period."

        matrix = [["Date", "Number of persons on date"]]
        for series in results:
            matrix[0].append(series["label"])
            row = [strip_datetime_seconds(series["date"])]
            for idx, val in enumerate(series["values"]):
                initial_count = series["values"][0]["count"]
                count = val["count"]
                if idx == 0:
                    row.append(format_number(count))
                    row.append("100%")
                elif initial_count != 0:
                    row.append(format_percentage(count / initial_count))
                else:
                    row.append("0%")
            matrix.append(row)

        date_from = strip_datetime_seconds(results[0]["date"])
        date_to = strip_datetime_seconds(results[-1]["date"])
        return f"Date range: {date_from} to {date_to}\nTime interval: {period}\n{format_matrix(matrix)}"

    @property
    def _period(self) -> RetentionPeriod:
        return self._query.retentionFilter.period or RetentionPeriod.DAY
