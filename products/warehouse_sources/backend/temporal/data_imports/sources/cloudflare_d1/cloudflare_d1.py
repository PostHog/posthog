import re
from collections.abc import Iterator
from datetime import date, datetime
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
INVALID_ID_MESSAGE = "Enter the account ID and database ID as shown in the Cloudflare dashboard, without a URL."

# Account and database ids are hex or UUID strings; anything else can't be part of the API path.
_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
# Names D1 reserves for its own bookkeeping and SQLite's internal tables.
_HIDDEN_TABLE_PREFIXES = ("_cf_", "sqlite_")


@frozen
class D1ResumeConfig:
    """Where the next page starts: a rowid for keyset paging, or an offset otherwise.

    `last_value` is the incremental column's value on the last row handed over, which keeps the
    keyset stable when many rows share one value.
    """

    table: str
    last_rowid: int | None = None
    last_value: Any = None
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

    def count_rows(self, table: str) -> int | None:
        rows = self.query(f"SELECT count(*) AS n FROM {quote_identifier(table)}")
        return int(rows[0][0]["n"]) if rows and rows[0] else None


def _sql_param(value: Any) -> str:
    # The query endpoint binds parameters as strings; SQLite's column affinity converts them back
    # to numbers when the column is numeric.
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _cursor_expression(sql: str, field_type: IncrementalFieldType | None) -> str:
    """The expression to order and compare an incremental value by.

    SQLite stores dates as text in whatever form the app wrote ("2024-01-02 03:04:05",
    "2024-01-02T03:04:05Z"), and the pipeline hands the watermark back as an ISO datetime. Plain
    text comparison of two forms is wrong, so both sides go through strftime, which keeps
    milliseconds and folds a UTC offset into UTC.
    """
    if field_type in (IncrementalFieldType.DateTime, IncrementalFieldType.Date, IncrementalFieldType.Timestamp):
        return f"strftime('%Y-%m-%d %H:%M:%f', {sql})"
    return sql


def _page_query(
    table: D1Table,
    incremental_field: str | None,
    field_type: IncrementalFieldType | None,
    watermark: Any,
    position: D1ResumeConfig,
) -> tuple[str, list[str]]:
    params: list[str] = []
    where: list[str] = []
    tiebreak = ["rowid"] if table.has_rowid else [quote_identifier(key) for key in table.primary_keys]
    if incremental_field is None:
        order = tiebreak or ["1"]
        if table.has_rowid and position.last_rowid is not None:
            where.append(f"rowid > {int(position.last_rowid)}")
    else:
        column = quote_identifier(incremental_field)
        cursor = _cursor_expression(column, field_type)
        bound = _cursor_expression("?", field_type)
        order = [cursor, *tiebreak]
        # NULL never satisfies a watermark comparison, so the pipeline could never advance past a
        # NULL row; leaving them out keeps every page's rows inside the cursor's reach.
        where.append(f"{column} IS NOT NULL")
        if table.has_rowid and position.last_rowid is not None:
            last_rowid = int(position.last_rowid)
            where.append(f"({cursor} > {bound} OR ({cursor} = {bound} AND rowid > {last_rowid}))")
            params.extend([_sql_param(position.last_value), _sql_param(position.last_value)])
        elif watermark is not None:
            where.append(f"{cursor} > {bound}")
            params.append(_sql_param(watermark))
    select = "rowid AS __rowid, *" if table.has_rowid else "*"
    sql = f"SELECT {select} FROM {quote_identifier(table.name)}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {', '.join(order)} LIMIT {PAGE_SIZE}"
    if not table.has_rowid:
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
    position = D1ResumeConfig(table=table.name)
    if manager.can_resume():
        saved = manager.load_state()
        if saved is not None and saved.table == table.name:
            position = saved
    while True:
        sql, params = _page_query(table, incremental_field, field_type, watermark, position)
        rows = client.query(sql, params)[0]
        if not rows:
            return
        last = rows[-1]
        if table.has_rowid:
            position = D1ResumeConfig(
                table=table.name,
                last_rowid=last["__rowid"],
                last_value=last.get(incremental_field) if incremental_field else None,
            )
            for row in rows:
                row.pop("__rowid", None)
        else:
            position = D1ResumeConfig(table=table.name, offset=position.offset + len(rows))
        # Staged before the yield it covers, so a hand-off resumes after this page.
        manager.save_state(position)
        yield rows
        if len(rows) < PAGE_SIZE:
            return
