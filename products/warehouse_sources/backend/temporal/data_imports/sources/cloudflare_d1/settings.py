from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalFieldType

BASE_URL = "https://api.cloudflare.com/client/v4"
# D1 caps a single query at 30 s and a statement at 100 KB; 1,000 rows keeps a wide-row page well
# under the response sizes the API answers quickly.
PAGE_SIZE = 1000
# PRAGMA table_info per table is one statement each; D1 runs a semicolon-joined batch in one
# request, so schema discovery costs one request per this many tables.
TABLES_PER_DISCOVERY_REQUEST = 50
# D1 stops a query at 30 s. Four attempts at a 60 s read stay inside the 5 minute contract budget.
REQUEST_TIMEOUT = (10, 60)


@frozen
class D1Table:
    name: str
    # Views and WITHOUT ROWID tables have no rowid; the latter keyset on their primary key.
    has_rowid: bool
    columns: tuple[tuple[str, str, bool], ...]
    primary_keys: tuple[str, ...]


def incremental_type_for_declared_type(declared_type: str) -> IncrementalFieldType | None:
    """Map a SQLite declared column type to the incremental type the pipeline compares with.

    SQLite column affinity is decided by substrings of the declared type, so the same rules apply
    here. Dates stored as ISO 8601 text compare correctly as text, so date and datetime columns are
    offered as dates and datetimes.
    """
    upper = declared_type.upper()
    if "INT" in upper:
        return IncrementalFieldType.Integer
    if "TIME" in upper and "DATE" not in upper and "TIMESTAMP" not in upper:
        # A clock time alone has no date to compare against the pipeline's datetime watermark.
        return None
    if "DATE" in upper and "TIME" not in upper:
        return IncrementalFieldType.Date
    if any(token in upper for token in ("DATE", "TIME")):
        return IncrementalFieldType.DateTime
    if any(token in upper for token in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
        return IncrementalFieldType.Numeric
    return None
