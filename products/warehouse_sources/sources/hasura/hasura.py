from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from products.warehouse_sources.sources.hasura.settings import (
    ADMIN_SECRET_HEADER,
    DEFAULT_GRAPHQL_PATH,
    PAGE_SIZE,
    REQUEST_TIMEOUT,
    VALIDATION_TIMEOUT,
    HasuraColumn,
    HasuraTable,
)
from products.warehouse_sources.sources.sdk import (
    IncrementalFieldType,
    ResumableSourceManager,
    coerce_date,
    format_datetime,
    frozen,
    is_url_allowed,
    make_tracked_session,
    raise_for_retryable_status,
    raise_for_status_redacted,
    vendor_retry,
)

# Prefixes of the messages raised below. `get_non_retryable_errors` matches on them.
ACCESS_DENIED_ERROR = "Hasura access denied"
TABLE_MISSING_ERROR = "Hasura no longer exposes the table"
INCREMENTAL_FIELD_ERROR = "Hasura can't sync this table incrementally"

_TYPE_REF = "kind name ofType { kind name ofType { kind name ofType { kind name } } }"
INTROSPECTION_QUERY = f"""query PostHogHasuraIntrospection {{
  __schema {{
    queryType {{ name }}
    types {{
      kind
      name
      fields {{ name args {{ name type {{ {_TYPE_REF} }} }} type {{ {_TYPE_REF} }} }}
      inputFields {{ name type {{ {_TYPE_REF} }} }}
    }}
  }}
}}"""
VALIDATION_QUERY = "query PostHogHasuraValidation { __schema { queryType { name } } }"

# The arguments Hasura generates on the list field of every tracked table and view.
_TABLE_ARGUMENTS = frozenset({"limit", "offset", "order_by", "where"})


class HasuraConfigError(Exception):
    pass


class HasuraAccessDeniedError(Exception):
    pass


class HasuraGraphQLError(Exception):
    pass


@frozen
class HasuraResumeConfig:
    """Where the next page starts.

    `keys` are the columns the read orders by: the incremental column first when there is one, then
    the primary key. `last_values` are their values on the last row handed over. A table without a
    primary key has no keys and pages by `offset`.
    """

    keys: list[str]
    last_values: list[Any] | None = None
    offset: int = 0


def resolve_graphql_url(raw_url: str) -> str:
    """Normalize the URL the user typed and check that PostHog may send the admin secret there.

    Users paste the project URL from Hasura Cloud (`https://x.hasura.app`) as often as the full
    endpoint, so an empty path gets Hasura's fixed `/v1/graphql` path.
    """
    url = (raw_url or "").strip()
    if not url:
        raise HasuraConfigError("Enter the URL of your Hasura GraphQL endpoint.")
    if "://" not in url:
        url = f"https://{url}"
    parts = urlsplit(url)
    # The admin secret rides in a header, so plain http would expose it on the network path.
    if parts.scheme != "https" or not parts.hostname:
        raise HasuraConfigError(
            "The Hasura GraphQL endpoint must be an https URL, for example https://my-project.hasura.app/v1/graphql."
        )
    path = parts.path.rstrip("/") or DEFAULT_GRAPHQL_PATH
    url = urlunsplit(("https", parts.netloc, path, parts.query, ""))
    # The host is user input. Reject localhost, cloud metadata, internal domains and private IPs
    # before the secret leaves the worker. This runs at validation and again on every sync.
    allowed, reason = is_url_allowed(url)
    if not allowed:
        raise HasuraConfigError(f"PostHog can't connect to this Hasura URL: {reason}")
    return url


def _render_type(type_ref: dict[str, Any]) -> str:
    kind = type_ref.get("kind")
    if kind == "NON_NULL":
        return f"{_render_type(type_ref['ofType'])}!"
    if kind == "LIST":
        return f"[{_render_type(type_ref['ofType'])}]"
    return str(type_ref.get("name"))


def _named_type(type_ref: dict[str, Any] | None) -> dict[str, Any]:
    while type_ref is not None and type_ref.get("kind") in ("NON_NULL", "LIST"):
        type_ref = type_ref.get("ofType")
    return type_ref or {}


def _is_list(type_ref: dict[str, Any] | None) -> bool:
    while type_ref is not None and type_ref.get("kind") == "NON_NULL":
        type_ref = type_ref.get("ofType")
    return type_ref is not None and type_ref.get("kind") == "LIST"


def _is_required(type_ref: dict[str, Any] | None) -> bool:
    return type_ref is not None and type_ref.get("kind") == "NON_NULL"


def _columns_of(object_type: dict[str, Any]) -> tuple[HasuraColumn, ...]:
    columns = []
    for field in object_type.get("fields") or []:
        named = _named_type(field.get("type"))
        if named.get("kind") not in ("SCALAR", "ENUM") or _is_list(field.get("type")):
            continue
        # A computed field whose SQL function needs arguments can't be selected without them.
        if any(_is_required(arg.get("type")) for arg in field.get("args") or []):
            continue
        columns.append(
            HasuraColumn(
                name=field["name"], scalar=str(named.get("name")), nullable=not _is_required(field.get("type"))
            )
        )
    return tuple(columns)


def _primary_keys(
    table_field: str, type_name: str, root_fields: list[dict[str, Any]], column_names: set[str]
) -> tuple[str, ...]:
    """The arguments of the table's `_by_pk` field, which Hasura generates only for a primary key.

    A custom root field name hides the `_by_pk` suffix, so a single other field that returns one row
    of the type by required column arguments counts too.
    """
    candidates: dict[str, tuple[str, ...]] = {}
    for field in root_fields:
        field_type = field.get("type")
        if _is_list(field_type) or _named_type(field_type).get("name") != type_name:
            continue
        args = field.get("args") or []
        names = tuple(arg["name"] for arg in args)
        if args and all(_is_required(arg.get("type")) for arg in args) and set(names) <= column_names:
            candidates[field["name"]] = names
    if f"{table_field}_by_pk" in candidates:
        return candidates[f"{table_field}_by_pk"]
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    return ()


def parse_tables(schema: dict[str, Any]) -> dict[str, HasuraTable]:
    """Read the tables and views a Hasura introspection result exposes, keyed by root field name."""
    types = {t["name"]: t for t in schema.get("types") or [] if t.get("name")}
    query_type = types.get((schema.get("queryType") or {}).get("name") or "query_root") or {}
    root_fields: list[dict[str, Any]] = query_type.get("fields") or []

    tables: dict[str, HasuraTable] = {}
    for field in root_fields:
        name = field.get("name") or ""
        field_type = field.get("type")
        object_type = types.get(_named_type(field_type).get("name") or "") or {}
        if name.startswith("__") or not _is_list(field_type) or object_type.get("kind") != "OBJECT":
            continue
        args = {arg["name"]: arg for arg in field.get("args") or []}
        if not _TABLE_ARGUMENTS <= args.keys() or any(_is_required(arg.get("type")) for arg in args.values()):
            continue
        columns = _columns_of(object_type)
        if not columns:
            continue
        column_names = {column.name for column in columns}
        order_by_input = types.get(_named_type(args["order_by"].get("type")).get("name") or "") or {}
        orderable = tuple(
            input_field["name"]
            for input_field in order_by_input.get("inputFields") or []
            if input_field["name"] in column_names and _named_type(input_field.get("type")).get("kind") == "ENUM"
        )
        tables[name] = HasuraTable(
            name=name,
            where_type=_render_type(args["where"]["type"]),
            order_by_type=_render_type(args["order_by"]["type"]),
            columns=columns,
            primary_keys=_primary_keys(name, object_type["name"], root_fields, column_names),
            orderable_columns=orderable,
        )
    return tables


class HasuraClient:
    def __init__(self, graphql_url: str, admin_secret: str) -> None:
        self.url = resolve_graphql_url(graphql_url)
        # Redirects stay off: the host was checked above, and a redirect could move the secret elsewhere.
        self.session = make_tracked_session(
            headers={ADMIN_SECRET_HEADER: admin_secret},
            redact_values=(admin_secret,),
            allow_redirects=False,
        )

    def _post(
        self, query: str, variables: dict[str, Any] | None, timeout: tuple[float, float], require_data: bool = True
    ) -> dict[str, Any]:
        response = self.session.post(self.url, json={"query": query, "variables": variables or {}}, timeout=timeout)
        raise_for_retryable_status(response, vendor="Hasura", url=self.url)
        raise_for_status_redacted(response, url=self.url)
        try:
            payload = response.json()
        except ValueError as error:
            raise HasuraGraphQLError(f"{self.url} did not answer with a GraphQL response") from error
        if not isinstance(payload, dict):
            if require_data:
                raise HasuraGraphQLError(f"{self.url} did not answer with a GraphQL response")
            return {}

        # Hasura answers a bad admin secret and a bad query with HTTP 200 and an `errors` list.
        errors = payload.get("errors")
        if errors:
            details = [error for error in errors if isinstance(error, dict)] or [{"message": str(errors)}]
            codes = {str((error.get("extensions") or {}).get("code", "")) for error in details}
            message = "; ".join(str(error.get("message", "")) for error in details)
            if "access-denied" in codes:
                raise HasuraAccessDeniedError(f"{ACCESS_DENIED_ERROR}: {message}")
            raise HasuraGraphQLError(f"Hasura GraphQL error ({', '.join(sorted(codes))}): {message}")
        data = payload.get("data")
        if not isinstance(data, dict):
            if require_data:
                raise HasuraGraphQLError(f"{self.url} did not answer with a GraphQL response")
            return {}
        return data

    @vendor_retry()
    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._post(query, variables, REQUEST_TIMEOUT)

    def validate(self) -> None:
        """One cheap request with no retries. Hasura checks the admin secret before it reads the query.

        Only an access-denied answer or a failed request fails it. Schema discovery reads the tables.
        """
        self._post(VALIDATION_QUERY, None, VALIDATION_TIMEOUT, require_data=False)

    def get_tables(self) -> dict[str, HasuraTable]:
        schema = self.execute(INTROSPECTION_QUERY).get("__schema")
        if not isinstance(schema, dict):
            raise HasuraGraphQLError(f"{self.url} did not answer the introspection query")
        return parse_tables(schema)


def format_watermark(value: Any, field_type: IncrementalFieldType) -> Any:
    if field_type == IncrementalFieldType.Integer:
        return int(value)
    if field_type == IncrementalFieldType.Date:
        parsed = coerce_date(value)
        if parsed is None:
            raise ValueError(f"Cannot read {value!r} as a date")
        return parsed.isoformat()
    return format_datetime(value, "iso_z_micros")


def _after(keys: list[str], values: list[Any]) -> dict[str, Any]:
    """Rows that sort after `values` in the order of `keys`: (k1 > v1) or (k1 = v1 and k2 > v2) or ..."""
    clauses: list[dict[str, Any]] = []
    for index, key in enumerate(keys):
        conditions: list[dict[str, Any]] = [{k: {"_eq": v}} for k, v in zip(keys[:index], values[:index])]
        conditions.append({key: {"_gt": values[index]}})
        clauses.append(conditions[0] if len(conditions) == 1 else {"_and": conditions})
    return clauses[0] if len(clauses) == 1 else {"_or": clauses}


def _page_document(table: HasuraTable) -> str:
    fields = " ".join(column.name for column in table.columns)
    return (
        f"query PostHogHasuraPage($limit: Int!, $offset: Int, $where: {table.where_type}, "
        f"$orderBy: {table.order_by_type}) {{ {table.name}(limit: $limit, offset: $offset, where: $where, "
        f"order_by: $orderBy) {{ {fields} }} }}"
    )


def iter_table_rows(
    client: HasuraClient,
    table: HasuraTable,
    incremental_field: str | None,
    watermark: Any,
    manager: ResumableSourceManager[HasuraResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    keyset = list(table.keyset_columns)
    base_where: list[dict[str, Any]] = []
    if incremental_field is not None:
        field_type = table.incremental_type(incremental_field)
        if field_type is None or not keyset:
            raise HasuraGraphQLError(
                f"{INCREMENTAL_FIELD_ERROR} on {incremental_field}: it needs a primary key and an orderable "
                "timestamp, date or integer column"
            )
        keys = [incremental_field, *(key for key in keyset if key != incremental_field)]
        # Rows with no value sort last and can't be compared with a watermark, so an incremental
        # read leaves them out on every run, the first one too.
        base_where.append({incremental_field: {"_is_null": False}})
        if watermark is not None:
            # Inclusive, so rows written at the stored value after the last run read it come back.
            # The merge on the primary key keeps them single.
            base_where.append({incremental_field: {"_gte": format_watermark(watermark, field_type)}})
    else:
        keys = keyset

    order_by = [{key: "asc"} for key in keys] or [{column: "asc"} for column in table.orderable_columns]
    document = _page_document(table)

    position = manager.load_state() if manager.can_resume() else None
    if position is None or position.keys != keys:
        position = HasuraResumeConfig(keys=keys)

    while True:
        where = list(base_where)
        variables: dict[str, Any] = {"limit": PAGE_SIZE, "orderBy": order_by}
        if keys:
            if position.last_values is not None:
                where.append(_after(keys, position.last_values))
        else:
            variables["offset"] = position.offset
        if where:
            variables["where"] = where[0] if len(where) == 1 else {"_and": where}

        rows = client.execute(document, variables).get(table.name)
        if not isinstance(rows, list):
            raise HasuraGraphQLError(f"Hasura returned no list for {table.name}")
        # Only an empty page ends the read: a page shorter than the limit can also come from a row
        # limit on the server, and stopping there would drop the rest of the table.
        if not rows:
            return

        if keys:
            last_values = [rows[-1].get(key) for key in keys]
            if last_values == position.last_values:
                raise HasuraGraphQLError(f"Hasura returned the same page of {table.name} twice")
            position = HasuraResumeConfig(keys=keys, last_values=last_values)
        else:
            position = HasuraResumeConfig(keys=keys, offset=position.offset + len(rows))
        # Staged before the yield it covers, so a hand-off resumes after this page.
        manager.save_state(position)
        yield rows


def is_access_denied(error: BaseException) -> bool:
    if isinstance(error, HasuraAccessDeniedError):
        return True
    return isinstance(error, requests.HTTPError) and getattr(error.response, "status_code", None) in (401, 403)
