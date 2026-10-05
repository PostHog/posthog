"""The rows that one precompute job stores: the rows a repository created in a span of whole days.

A job stores a row once, under the day the row was created, because that day never changes. Other
rows can still change what a stored row says: a later job attempt can fail a run that had passed,
and an earlier attempt shows that a job row is a re-listed copy. So a scan for such rows reaches a
fixed slack before or after the span.

The bounds are SQL expressions that give date-only strings. A scan compares them with the raw
ISO-8601 ``created_at`` strings, which is the one comparison that lets a warehouse scan skip files.
"""

from posthog.dataclasses import frozen


@frozen
class CreatedWindow:
    start: str
    end: str
    earlier_start: str
    later_end: str

    def rows(self, column: str = "created_at") -> str:
        """The rows the job stores."""
        return f"{column} >= {self.start} AND {column} < {self.end}"

    def rows_and_earlier(self, column: str = "created_at") -> str:
        return f"{column} >= {self.earlier_start} AND {column} < {self.end}"

    def rows_and_later(self, column: str = "created_at") -> str:
        return f"{column} >= {self.start} AND {column} < {self.later_end}"

    def rows_and_around(self, column: str = "created_at") -> str:
        return f"{column} >= {self.earlier_start} AND {column} < {self.later_end}"
