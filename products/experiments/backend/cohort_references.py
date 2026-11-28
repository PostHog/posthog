"""The cohorts that an experiment filters on, in its exposure criteria, its metrics and its linked shared metrics."""

from collections.abc import Iterable
from typing import Any

# A cohort filter can hold the cohort id as a number or as a string. `cohort_ids` reads the same filters in Python.
COHORT_FILTER_JSONPATH = '$.** ? (@.type == "cohort" && (@.value == $id || @.value == $id_text))'


def cohort_ids(documents: Iterable[Any]) -> set[int]:
    """The ids that the cohort filters anywhere in the JSON documents name."""
    ids: set[int] = set()
    pending = list(documents)
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if node.get("type") == "cohort" and (cohort_id := _cohort_id(node.get("value"))) is not None:
                ids.add(cohort_id)
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return ids


def _cohort_id(value: Any) -> int | None:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    # Cohort ids fit the 32-bit primary key, and a larger number would make the cohort lookup fail.
    if isinstance(value, int) and not isinstance(value, bool) and 0 < value < 2**31:
        return value
    return None
