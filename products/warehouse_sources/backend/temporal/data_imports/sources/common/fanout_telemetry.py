from typing import Literal

from structlog.types import FilteringBoundLogger

FanoutParentSource = Literal["api", "warehouse"]

FANOUT_PARENT_ROWS_CONSUMED = "data_imports.fanout_parent_rows_consumed"


def log_fanout_parent_rows_consumed(
    logger: FilteringBoundLogger,
    *,
    parent_source: FanoutParentSource,
    rows_total: int,
    page_rows: int | None = None,
) -> None:
    """Report how many parent rows a fan-out sweep consumed, and which parent source served them.

    Every fan-out emits this through one helper so that a single query can compare the two parent
    sources for one schema. That comparison is the only way to detect a warehouse parent that is
    missing rows the API listing still returns. A webhook-maintained parent can be missing rows,
    because its table holds only what its drains delivered.

    `page_rows` is for a caller that emits once per parent page and carries `rows_total` as a
    running total. A caller that emits once at the end of its sweep omits it.

    Lives in a leaf module (no deltalake or pyarrow) so that any source can import it.
    """
    per_page_fields: dict[str, int] = {} if page_rows is None else {"page_rows": page_rows}
    logger.info(
        FANOUT_PARENT_ROWS_CONSUMED,
        parent_source=parent_source,
        rows_total=rows_total,
        **per_page_fields,
    )
