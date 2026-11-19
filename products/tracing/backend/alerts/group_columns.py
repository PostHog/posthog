"""The columns a grouped traces alert may split on, named as a reader knows them.

Kept apart from the query layer, because the wording imports it from `ready()`.
"""

from typing import Final

# Both are LowCardinality columns of `trace_spans` and both sit in its sort key.
GROUP_COLUMNS: Final[dict[str, str]] = {"service_name": "Service", "name": "Operation"}
