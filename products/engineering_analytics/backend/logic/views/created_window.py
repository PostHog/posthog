"""The rows that one precompute job stores: the rows a repository created in a span of whole days.

A job stores a row once, under the day the row was created, because that day never changes. Other
rows can still change what a stored row says: a later job attempt can fail a run that had passed,
and an earlier attempt shows that a job row is a re-listed copy. So a scan for such rows reaches a
fixed slack before or after the span.

The bounds are SQL expressions that give date-only strings. A scan compares them with the raw
ISO-8601 ``created_at`` strings, which is the one comparison that lets a warehouse scan skip files.
"""

from posthog.dataclasses import frozen


def _day(moment: str) -> str:
    return f"formatDateTime(toTimeZone({moment}, 'UTC'), '%Y-%m-%d')"


@frozen
class CreatedWindow:
    """The framework's span of whole days, from ``{time_window_min}`` to ``{time_window_max}``, with
    ``slack_days`` of reach on either side."""

    slack_days: int

    def rows(self, column: str = "created_at") -> str:
        """The rows the job stores."""
        return self._between(column, "{time_window_min}", "{time_window_max}")

    def rows_and_earlier(self, column: str = "created_at") -> str:
        return self._between(column, self._earlier_start, "{time_window_max}")

    def rows_and_later(self, column: str = "created_at") -> str:
        return self._between(column, "{time_window_min}", self._later_end)

    def rows_and_around(self, column: str = "created_at") -> str:
        return self._between(column, self._earlier_start, self._later_end)

    @property
    def _earlier_start(self) -> str:
        return f"{{time_window_min}} - INTERVAL {self.slack_days} DAY"

    @property
    def _later_end(self) -> str:
        return f"{{time_window_max}} + INTERVAL {self.slack_days} DAY"

    @staticmethod
    def _between(column: str, start: str, end: str) -> str:
        return f"{column} >= {_day(start)} AND {column} < {_day(end)}"
