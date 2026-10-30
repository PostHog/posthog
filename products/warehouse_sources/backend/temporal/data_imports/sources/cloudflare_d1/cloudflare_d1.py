import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

from requests import Response, Session

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare_d1.settings import (
    BASE_URL,
    PAGE_SIZE,
    REQUEST_TIMEOUT,
    TABLES_PER_DISCOVERY_REQUEST,
    D1Table,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.types import IncrementalFieldType

INVALID_TOKEN_MESSAGE = (
    "Cloudflare rejected your API token. Create a token with D1 read permission for this account, then reconnect."
)
PERMISSION_MESSAGE = (
    "Your Cloudflare API token can't read this D1 database. Give it D1 read permission, then reconnect."
)
NOT_FOUND_MESSAGE = "Cloudflare couldn't find that D1 database. Check the account ID and database ID, then reconnect."
UNREACHABLE_MESSAGE = "Couldn't reach Cloudflare to verify the token. Try again in a moment."
INVALID_ID_MESSAGE = "Enter the account ID and database ID as shown in the Cloudflare dashboard, without a URL."

# Account and database ids are hex or UUID strings; anything else can't be part of the API path.
_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
# Names D1 reserves for its own bookkeeping and SQLite's internal tables.
_HIDDEN_TABLE_PREFIXES = ("_cf_", "sqlite_")


@frozen
class D1ResumeConfig:
    """Where the next page starts: the key values of the last row handed over, or an offset.

    `last_values` lines up with the keyset columns: the incremental column first when there is one,
    then the rowid or the primary key columns. A view without either pages by `offset`. The resume
    state is kept per job, and a job syncs one table, so it needs no table name.
    """

    last_values: list[Any] | None = None
    offset: int = 0


class D1QueryError(Exception):
    pass


def validate_identifier(value: str) -> str:
    stripped = value.strip()
    if not _ID_RE.match(stripped):
        raise ValueError(INVALID_ID_MESSAGE)
    return stripped


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _session(api_token: str) -> Session:
    return make_tracked_session(
        # Every D1 query is a POST, which the default policy never retries. The source only sends
        # read-only statements, so a 429 or a transient 5xx is safe to retry.
        retry=DEFAULT_RETRY.new(allowed_methods=frozenset(["GET", "POST"])),
        headers={"Authorization": f"Bearer {api_token}"},
        redact_values=(api_token,),
        allow_redirects=False,
    )


def _cloudflare_error(response: Response) -> str:
    try:
        errors = response.json().get("errors") or []
    except Exception:
        return response.text[:200]
    return "; ".join(str(error.get("message")) for error in errors if isinstance(error, dict)) or "unknown error"


class D1Client:
    def __init__(self, api_token: str, account_id: str, database_id: str) -> None:
        self._session = _session(api_token)
        self._database_url = (
            f"{BASE_URL}/accounts/{validate_identifier(account_id)}/d1/database/{validate_identifier(database_id)}"
        )

    def get_database(self) -> Response:
        return self._session.get(self._database_url, timeout=REQUEST_TIMEOUT)

    def query(self, sql: str, params: list[Any] | None = None) -> list[list[dict[str, Any]]]:
        """Run one statement, or several joined by semicolons, and return each statement's rows."""
        response = self._session.post(
            f"{self._database_url}/query", json={"sql": sql, "params": params or []}, timeout=REQUEST_TIMEOUT
        )
        if response.status_code >= 400:
            # The SQL error text (no such table, syntax error) is in the envelope, not the status
            # line, so surface it instead of letting raise_for_status hide it.
            if response.status_code in (401, 403, 404):
                response.raise_for_status()
            raise D1QueryError(f"D1 query failed ({response.status_code}): {_cloudflare_error(response)}")
        body = response.json()
        if not body.get("success"):
            raise D1QueryError(f"D1 query failed: {_cloudflare_error(response)}")
        return [statement.get("results") or [] for statement in body.get("result") or []]

    def list_tables(self, names: list[str] | None = None) -> list[D1Table]:
        listing = self.query(
            "PRAGMA table_list; SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name"
        )
        rowid_tables = {row["name"] for row in listing[0] if not row.get("wr") and row.get("type") == "table"}
        wanted = [
            row["name"]
            for row in listing[1]
            if not row["name"].startswith(_HIDDEN_TABLE_PREFIXES) and (names is None or row["name"] in names)
        ]
        tables: list[D1Table] = []
        for start in range(0, len(wanted), TABLES_PER_DISCOVERY_REQUEST):
            chunk = wanted[start : start + TABLES_PER_DISCOVERY_REQUEST]
            infos = self.query("; ".join(f"PRAGMA table_info({quote_identifier(name)})" for name in chunk))
            for name, info in zip(chunk, infos):
                tables.append(
                    D1Table(
                        name=name,
                        has_rowid=name in rowid_tables,
                        columns=tuple((col["name"], col.get("type") or "", not col.get("notnull")) for col in info),
                        primary_keys=tuple(
                            col["name"] for col in sorted(info, key=lambda c: c.get("pk") or 0) if col.get("pk")
                        ),
                    )
                )
        return tables

    def leading_index_columns(self, tables: list[str]) -> dict[str, set[str]]:
        """The columns that lead an index, per table: a cursor on one of them can seek instead of scan."""
        if not tables:
            return {}
        indexes: list[tuple[str, str]] = []
        for start in range(0, len(tables), TABLES_PER_DISCOVERY_REQUEST):
            chunk = tables[start : start + TABLES_PER_DISCOVERY_REQUEST]
            listings = self.query("; ".join(f"PRAGMA index_list({quote_identifier(name)})" for name in chunk))
            indexes.extend((name, row["name"]) for name, listing in zip(chunk, listings) for row in listing)
        leading: dict[str, set[str]] = {name: set() for name in tables}
        for start in range(0, len(indexes), TABLES_PER_DISCOVERY_REQUEST):
            chunk_indexes = indexes[start : start + TABLES_PER_DISCOVERY_REQUEST]
            infos = self.query("; ".join(f"PRAGMA index_info({quote_identifier(index)})" for _, index in chunk_indexes))
            for (table, _), info in zip(chunk_indexes, infos):
                leading[table].update(row["name"] for row in info if row.get("seqno") == 0 and row.get("name"))
        return leading

    def count_rows(self, table: str) -> int | None:
        rows = self.query(f"SELECT count(*) AS n FROM {quote_identifier(table)}")
        return int(rows[0][0]["n"]) if rows and rows[0] else None


# SQLite answers to any of these names with the hidden integer key, unless a column took the name.
_ROWID_ALIASES = ("rowid", "_rowid_", "oid")
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_TYPES = (IncrementalFieldType.DateTime, IncrementalFieldType.Date, IncrementalFieldType.Timestamp)


def rowid_alias(table: D1Table) -> str | None:
    """A name that reaches the hidden rowid, or None when the table has none or every alias is a column."""
    if not table.has_rowid:
        return None
    taken = {name.lower() for name, _, _ in table.columns}
    return next((alias for alias in _ROWID_ALIASES if alias not in taken), None)


def _free_name(table: D1Table, base: str) -> str:
    taken = {name for name, _, _ in table.columns}
    name = base
    while name in taken:
        name = f"_{name}"
    return name


def _sql_param(value: Any) -> str:
    # The query endpoint binds parameters as strings; SQLite's column affinity converts them back
    # to numbers when the column is numeric.
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def watermark_like(sample: Any, watermark: Any, field_type: IncrementalFieldType | None) -> Any:
    """The watermark in the form the column stores, so a plain comparison can use an index.

    SQLite keeps dates as whatever text the app wrote. The pipeline hands the watermark back as a
    datetime, and its ISO text compares wrongly against "2024-01-02 03:04:05". The bound drops
    fractions and zone suffixes: a value's own suffix then sorts after the bound, so the inclusive
    comparison keeps every row of the watermark's second.
    """
    if field_type not in _DATE_TYPES or not isinstance(watermark, datetime | date):
        return watermark
    moment = watermark if isinstance(watermark, datetime) else datetime(watermark.year, watermark.month, watermark.day)
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    if isinstance(sample, int | float):
        seconds = moment.replace(tzinfo=UTC).timestamp()
        # Epoch milliseconds already have 13 digits.
        return int(seconds * 1000) if sample > 10**11 else int(seconds)
    if isinstance(sample, str) and _DATE_ONLY_RE.match(sample):
        return moment.date().isoformat()
    separator = "T" if isinstance(sample, str) and "T" in sample else " "
    return moment.strftime(f"%Y-%m-%d{separator}%H:%M:%S")


def _keyset(table: D1Table, incremental_field: str | None) -> list[str]:
    alias = rowid_alias(table)
    tiebreak = [alias] if alias else list(table.primary_keys)
    declared = {name: declared_type.upper() for name, declared_type, _ in table.columns}
    if not alias and any(not declared.get(key) or "BLOB" in declared[key] for key in tiebreak):
        # A key that can hold a BLOB can't be bound back from text: SQLite sorts every BLOB above
        # every string, so the keyset would serve the first page forever. Page by offset instead.
        return []
    if not tiebreak:
        return []
    return ([incremental_field] if incremental_field else []) + tiebreak


def pages_by_keyset(table: D1Table) -> bool:
    """Whether the table has a rowid or a usable primary key. Without one it pages by offset."""
    return bool(_keyset(table, None))


def integer_primary_key(table: D1Table) -> str | None:
    """The INTEGER PRIMARY KEY column, which is the rowid itself and so is always indexed."""
    if not table.has_rowid or len(table.primary_keys) != 1:
        return None
    declared = {name: declared_type.upper() for name, declared_type, _ in table.columns}
    return table.primary_keys[0] if declared.get(table.primary_keys[0]) == "INTEGER" else None


def _page_query(
    table: D1Table,
    incremental_field: str | None,
    bound: Any,
    position: D1ResumeConfig,
    keyset: list[str],
    rowid_tag: str,
) -> tuple[str, list[str]]:
    params: list[str] = []
    where: list[str] = []
    alias = rowid_alias(table)
    if incremental_field is not None:
        column = quote_identifier(incremental_field)
        # NULL never satisfies a watermark comparison, so the pipeline could never advance past a
        # NULL row; leaving them out keeps every page's rows inside the cursor's reach.
        where.append(f"{column} IS NOT NULL")
        if bound is not None:
            # Inclusive: rows of the watermark's own second come again, and the merge keeps one.
            where.append(f"{column} >= ?")
            params.append(_sql_param(bound))
    if keyset and position.last_values is not None:
        keys = ", ".join(quote_identifier(key) if key != alias else key for key in keyset)
        values = []
        for key, value in zip(keyset, position.last_values):
            if key == alias:
                values.append(str(int(value)))
            else:
                values.append("?")
                params.append(_sql_param(value))
        where.append(f"({keys}) > ({', '.join(values)})")
    select = f"{alias} AS {quote_identifier(rowid_tag)}, *" if alias else "*"
    order = [quote_identifier(key) if key != alias else key for key in keyset]
    if not order:
        order = [quote_identifier(incremental_field)] if incremental_field else ["1"]
    sql = f"SELECT {select} FROM {quote_identifier(table.name)}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {', '.join(order)} LIMIT {PAGE_SIZE}"
    if not keyset:
        sql += f" OFFSET {position.offset}"
    return sql, params


def iter_table_rows(
    client: D1Client,
    table: D1Table,
    incremental_field: str | None,
    field_type: IncrementalFieldType | None,
    watermark: Any,
    manager: ResumableSourceManager[D1ResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    if incremental_field is not None and incremental_field not in {name for name, _, _ in table.columns}:
        # SQLite reads an unknown double-quoted name as a string literal, so the query would run
        # and match nothing instead of failing.
        raise D1QueryError(f"no such column: {incremental_field}")
    keyset = _keyset(table, incremental_field)
    if incremental_field is not None and not keyset:
        # An offset counted under one watermark skips rows once the next attempt starts from a later one.
        raise D1QueryError(f"incremental sync needs a rowid or a primary key on {table.name}")
    alias = rowid_alias(table)
    rowid_tag = _free_name(table, "__posthog_rowid")
    bound = None
    if incremental_field is not None and watermark is not None:
        column = quote_identifier(incremental_field)
        # The newest value shows the form the app writes today.
        sample = client.query(
            f"SELECT {column} AS v FROM {quote_identifier(table.name)} WHERE {column} IS NOT NULL "
            f"ORDER BY {column} DESC LIMIT 1"
        )
        rows = sample[0] if sample else []
        bound = watermark_like(rows[0]["v"] if rows else None, watermark, field_type)
    position = D1ResumeConfig()
    if manager.can_resume():
        position = manager.load_state() or position
    while True:
        sql, params = _page_query(table, incremental_field, bound, position, keyset, rowid_tag)
        rows = client.query(sql, params)[0]
        if not rows:
            return
        last = rows[-1]
        if keyset:
            position = D1ResumeConfig(last_values=[last[rowid_tag] if key == alias else last[key] for key in keyset])
        else:
            position = D1ResumeConfig(offset=position.offset + len(rows))
        if alias:
            for row in rows:
                del row[rowid_tag]
        # Staged before the yield it covers, so a hand-off resumes after this page.
        manager.save_state(position)
        yield rows
        if len(rows) < PAGE_SIZE:
            return
