from typing import Literal

from structlog.types import FilteringBoundLogger

FanoutParentSource = Literal["api", "warehouse"]

FANOUT_PARENT_ROWS_CONSUMED = "data_imports.fanout_parent_rows_consumed"


def log_fanout_parent_rows_consumed(
    logger: FilteringBoundLogger,
    *,
    parent_source: FanoutParentSource,
    rows_total: int,
    resumed: bool,
    page_rows: int | None = None,
) -> None:
    """Report how many parent rows a fan-out sweep consumed, and which source served them.

    Comparing that count across the two parent sources for one schema is how a warehouse parent
    that is missing rows gets found, because a webhook-maintained parent holds only what its
    drains delivered.

    `rows_total` counts the current attempt, so an attempt that resumed reports fewer rows than
    the sweep covers. `resumed` marks those lines, because a partial count and a genuinely short
    parent listing otherwise look the same.

    Emit often enough that the last line of an attempt carries its running total. A caller that
    emits once per parent page also sets `page_rows`.

    Lives in a leaf module (no deltalake or pyarrow) so that any source can import it.
    """
    per_page_fields: dict[str, int] = {} if page_rows is None else {"page_rows": page_rows}
    logger.info(
        FANOUT_PARENT_ROWS_CONSUMED,
        parent_source=parent_source,
        rows_total=rows_total,
        resumed=resumed,
        **per_page_fields,
    )
