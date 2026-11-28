import json
from collections import defaultdict
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from products.warehouse_sources.sources.hasura.settings import (
    ADMIN_SECRET_HEADER,
    DEFAULT_GRAPHQL_PATH,
    OFFSET_PAGE_SIZE,
    PAGE_SIZE,
    REQUEST_TIMEOUT,
    VALIDATION_TIMEOUT,
    HasuraColumn,
    HasuraTable,
)
from products.warehouse_sources.sources.sdk import (
    UNRESOLVED_HOST_REASON,
    IncrementalFieldType,
    ResumableSourceManager,
    TemporaryHostResolutionError,
    coerce_date,
    format_datetime,
    frozen,
    is_url_allowed,
    make_tracked_session,
    raise_for_retryable_status,
    raise_for_status_redacted,
    safe_url,
    suspend_adapter_retries,
    vendor_retry,
)

# Prefixes of the messages raised below. `get_non_retryable_errors` matches on them.
ACCESS_DENIED_ERROR = "Hasura access denied"
TABLE_MISSING_ERROR = "Hasura doesn't expose the table"
INCREMENTAL_FIELD_ERROR = "Hasura can't sync this table incrementally"
UNORDERED_TABLE_ERROR = "Hasura can't page through the table"
NAMING_CONVENTION_ERROR = "Hasura uses the graphql-default naming convention"
NAMESPACE_ERROR = "Hasura puts its root fields under a namespace"
REQUEST_FAILED_ERROR = "Hasura request failed"
URL_NOT_ALLOWED_ERROR = "PostHog can't connect to this Hasura URL"
# Postgres stops a query that runs longer than its `statement_timeout`; Hasura passes the text on.
STATEMENT_TIMEOUT_ERROR = "canceling statement due to statement timeout"

_TYPE_REF = "kind name ofType { kind name ofType { kind name ofType { kind name } } }"
_FIELDS = f"fields {{ name args {{ name type {{ {_TYPE_REF} }} }} type {{ {_TYPE_REF} }} }}"
_TYPE = f"kind name {_FIELDS} inputFields {{ name type {{ {_TYPE_REF} }} }}"
INTROSPECTION_QUERY = f"query PostHogHasuraIntrospection {{ __schema {{ queryType {{ name }} types {{ {_TYPE} }} }} }}"
# A sync needs one table, so it reads the root fields and that table's two types, not every type.
ROOT_FIELDS_QUERY = f"query PostHogHasuraRootFields {{ __schema {{ queryType {{ name {_FIELDS} }} }} }}"
TABLE_TYPES_QUERY = (
    "query PostHogHasuraTableTypes($object: String!, $orderBy: String!) "
    f"{{ object: __type(name: $object) {{ {_TYPE} }} orderBy: __type(name: $orderBy) {{ {_TYPE} }} }}"
)
VALIDATION_QUERY = "query PostHogHasuraValidation { __schema { queryType { name } } }"

# The arguments Hasura generates on the list field of every tracked table and view.
_TABLE_ARGUMENTS = frozenset({"limit", "offset", "order_by", "where"})


class HasuraConfigError(Exception):
    pass


class HasuraAccessDeniedError(Exception):
    pass


class HasuraGraphQLError(Exception):
    pass


class HasuraRequestError(Exception):
    """A failed connection, with a message that leaves out the endpoint's query string."""


class HasuraTimeoutError(Exception):
    """A read timeout. It is not resent at once: the database can still be running the slow query."""


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
    # Error messages and logs show the URL, so it must not carry a credential of its own.
    if parts.username or parts.password:
        raise HasuraConfigError("Remove the user name and password from the Hasura GraphQL endpoint URL.")
    path = parts.path.rstrip("/") or DEFAULT_GRAPHQL_PATH
    url = urlunsplit(("https", parts.netloc, path, parts.query, ""))
    # The host is user input. Reject localhost, cloud metadata, internal domains and private IPs
    # before the secret leaves the worker. This runs at validation and again on every sync.
    allowed, reason = is_url_allowed(url)
    if not allowed:
        if reason == UNRESOLVED_HOST_REASON:
            # A DNS blip, not a policy decision, so the sync retries it.
            raise TemporaryHostResolutionError(parts.hostname)
        raise HasuraConfigError(f"{URL_NOT_ALLOWED_ERROR}: {reason}")
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
                name=field["name"],
                scalar=str(named.get("name")),
                nullable=not _is_required(field.get("type")),
                enum=named.get("kind") == "ENUM",
            )
        )
    return tuple(columns)


def _single_row_fields(root_fields: list[dict[str, Any]]) -> dict[str, list[tuple[str, tuple[str, ...]]]]:
    """Root fields that return one row by required arguments, as (name, argument names) per row type."""
    by_type: dict[str, list[tuple[str, tuple[str, ...]]]] = defaultdict(list)
    for field in root_fields:
        field_type = field.get("type")
        args = field.get("args") or []
        if _is_list(field_type) or not args or not all(_is_required(arg.get("type")) for arg in args):
            continue
        type_name = _named_type(field_type).get("name")
        if type_name:
            by_type[type_name].append((field["name"], tuple(arg["name"] for arg in args)))
    return by_type


def _primary_keys(
    table_field: str, candidates: list[tuple[str, tuple[str, ...]]], column_names: set[str]
) -> tuple[str, ...]:
    """The arguments of the table's `_by_pk` field, which Hasura generates only for a primary key.

    A custom root field name hides the `_by_pk` suffix, so a single other field that returns one row
    of the type by required column arguments counts too.
    """
    matching = {name: args for name, args in candidates if set(args) <= column_names}
    if f"{table_field}_by_pk" in matching:
        return matching[f"{table_field}_by_pk"]
    if len(matching) == 1:
        return next(iter(matching.values()))
    return ()


def _check_naming_convention(root_fields: list[dict[str, Any]]) -> None:
    # The graphql-default convention renames `order_by` to `orderBy`, the `asc` order values to
    # `ASC` and `_is_null` to `_isNull`. The page queries here use the hasura-default names.
    if any(arg.get("name") == "orderBy" for field in root_fields for arg in field.get("args") or []):
        raise HasuraGraphQLError(
            f"{NAMING_CONVENTION_ERROR}, which PostHog can't read yet. Switch the source to the "
            "hasura-default naming convention to sync it."
        )


def _check_namespaces(root_fields: list[dict[str, Any]], types: dict[str, dict[str, Any]]) -> None:
    # A source with a root-field namespace nests its table fields in one object field (`mydb { orders }`).
    for field in root_fields:
        field_type = field.get("type")
        nested = types.get(_named_type(field_type).get("name") or "") or {}
        if field.get("args") or _is_list(field_type) or nested.get("kind") != "OBJECT":
            continue
        if any(_TABLE_ARGUMENTS <= {arg["name"] for arg in f.get("args") or []} for f in nested.get("fields") or []):
            raise HasuraGraphQLError(
                f"{NAMESPACE_ERROR} ({field.get('name')}), which PostHog can't read yet. Remove the "
                "root field namespace from the source in Hasura to sync it."
            )


def parse_tables(schema: dict[str, Any]) -> dict[str, HasuraTable]:
    """Read the tables and views a Hasura introspection result exposes, keyed by root field name."""
    types = {t["name"]: t for t in schema.get("types") or [] if t and t.get("name")}
    query_type = types.get((schema.get("queryType") or {}).get("name") or "query_root") or {}
    root_fields: list[dict[str, Any]] = query_type.get("fields") or []
    single_row_fields = _single_row_fields(root_fields)

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
            primary_keys=_primary_keys(name, single_row_fields.get(object_type["name"], []), column_names),
            orderable_columns=orderable,
        )
    if not tables:
        _check_naming_convention(root_fields)
        _check_namespaces(root_fields, types)
    return tables


def _error_message(error: dict[str, Any]) -> str:
    message = str(error.get("message", ""))
    # For the admin role, a database error ("database query error") carries the database's own
    # message under `extensions.internal.error`, such as a statement timeout.
    internal = ((error.get("extensions") or {}).get("internal") or {}).get("error") or {}
    if isinstance(internal, dict) and internal.get("message"):
        message = f"{message}: {internal['message']}"
    return message


def _decode(content: bytes, url: str, *, require_data: bool = True, exact: bool = False) -> dict[str, Any]:
    try:
        # `parse_float=Decimal` keeps every digit of a JSON number with a fraction or exponent.
        payload = json.loads(content, parse_float=Decimal) if exact else json.loads(content)
    except ValueError as error:
        raise HasuraGraphQLError(f"{safe_url(url)} did not answer with a GraphQL response") from error
    if not isinstance(payload, dict):
        if require_data:
            raise HasuraGraphQLError(f"{safe_url(url)} did not answer with a GraphQL response")
        return {}

    # Hasura answers a bad admin secret and a bad query with HTTP 200 and an `errors` list.
    errors = payload.get("errors")
    if errors:
        details = [error for error in errors if isinstance(error, dict)] or [{"message": str(errors)}]
        codes = {str((error.get("extensions") or {}).get("code", "")) for error in details}
        message = "; ".join(_error_message(error) for error in details)
        if "access-denied" in codes:
            raise HasuraAccessDeniedError(f"{ACCESS_DENIED_ERROR}: {message}")
        raise HasuraGraphQLError(f"Hasura GraphQL error ({', '.join(sorted(codes))}): {message}")
    data = payload.get("data")
    if not isinstance(data, dict):
        if require_data:
            raise HasuraGraphQLError(f"{safe_url(url)} did not answer with a GraphQL response")
        return {}
    return data


class HasuraClient:
    def __init__(self, graphql_url: str, admin_secret: str) -> None:
        self.url = resolve_graphql_url(graphql_url)
        # Redirects stay off: the host was checked above, and a redirect could move the secret elsewhere.
        self.session = make_tracked_session(
            headers={ADMIN_SECRET_HEADER: admin_secret},
            redact_values=(admin_secret,),
            allow_redirects=False,
        )

    def _send(self, query: str, variables: dict[str, Any] | None, timeout: tuple[float, float]) -> bytes:
        try:
            response = self.session.post(self.url, json={"query": query, "variables": variables or {}}, timeout=timeout)
        except requests.RequestException as error:
            # The requests message repeats the full URL, query string included, so it is replaced.
            # `from None` keeps that text out of the chained traceback in error tracking too.
            if isinstance(error, requests.ReadTimeout):
                raise HasuraTimeoutError(
                    f"{REQUEST_FAILED_ERROR}: {safe_url(self.url)} did not answer in time"
                ) from None
            raise HasuraRequestError(
                f"{REQUEST_FAILED_ERROR}: {type(error).__name__} for {safe_url(self.url)}"
            ) from None
        raise_for_retryable_status(response, vendor="Hasura", url=self.url)
        raise_for_status_redacted(response, url=self.url)
        return response.content

    # A read timeout is left to the activity retry, which resumes from the saved cursor later.
    @vendor_retry(retry_on=(HasuraRequestError,))
    def _send_with_retry(self, query: str, variables: dict[str, Any] | None) -> bytes:
        return self._send(query, variables, REQUEST_TIMEOUT)

    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        return _decode(self._send_with_retry(query, variables), self.url)

    def fetch_page(self, table: HasuraTable, document: str, variables: dict[str, Any]) -> list[dict[str, Any]]:
        content = self._send_with_retry(document, variables)
        rows = _decode(content, self.url).get(table.name)
        if not isinstance(rows, list):
            raise HasuraGraphQLError(f"Hasura returned no list for {table.name}")
        decimal_columns = table.decimal_columns
        if rows and decimal_columns:
            # A second, exact decode only for the decimal columns: Decimal values inside a json
            # column would not serialize, so every other column keeps the plain decode.
            exact_rows = _decode(content, self.url, exact=True).get(table.name) or []
            for row, exact_row in zip(rows, exact_rows):
                for column in decimal_columns:
                    value = exact_row.get(column)
                    if isinstance(value, int) and not isinstance(value, bool):
                        value = Decimal(value)
                    if column in row:
                        row[column] = value
        return rows

    def validate(self) -> None:
        """One cheap request with no retries. Hasura checks the admin secret before it reads the query.

        Only an access-denied answer or a failed request fails it. Schema discovery reads the tables.
        """
        with suspend_adapter_retries():
            content = self._send(VALIDATION_QUERY, None, VALIDATION_TIMEOUT)
        _decode(content, self.url, require_data=False)

    def get_tables(self) -> dict[str, HasuraTable]:
        schema = self.execute(INTROSPECTION_QUERY).get("__schema")
        if not isinstance(schema, dict):
            raise HasuraGraphQLError(f"{safe_url(self.url)} did not answer the introspection query")
        return parse_tables(schema)

    def get_named_tables(self, names: list[str]) -> dict[str, HasuraTable]:
        """Introspect only the named tables: the root fields, then each table's object and order_by types."""
        query_type = (self.execute(ROOT_FIELDS_QUERY).get("__schema") or {}).get("queryType")
        if not isinstance(query_type, dict):
            raise HasuraGraphQLError(f"{safe_url(self.url)} did not answer the introspection query")
        root_fields: list[dict[str, Any]] = query_type.get("fields") or []
        fields_by_name = {f.get("name"): f for f in root_fields}
        query_root = {"kind": "OBJECT", "name": query_type.get("name"), "fields": root_fields, "inputFields": None}
        tables: dict[str, HasuraTable] = {}
        for name in names:
            field = fields_by_name.get(name)
            args = {arg["name"]: arg for arg in (field or {}).get("args") or []}
            if field is None or "order_by" not in args:
                continue
            types = self.execute(
                TABLE_TYPES_QUERY,
                {
                    "object": _named_type(field.get("type")).get("name"),
                    "orderBy": _named_type(args["order_by"].get("type")).get("name"),
                },
            )
            schema = {
                "queryType": {"name": query_type.get("name")},
                "types": [query_root, types.get("object"), types.get("orderBy")],
            }
            if (table := parse_tables(schema).get(name)) is not None:
                tables[name] = table
        if not tables:
            _check_naming_convention(root_fields)
        return tables


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
    """Rows that sort after `values` in the order of `keys`: (k1 > v1) or (k1 = v1 and k2 > v2) or ...

    For more than one key, `k1 >= v1` is added as well. The database can't derive that range from the
    OR, and without it each page scans every row the read already passed.
    """
    clauses: list[dict[str, Any]] = []
    for index, key in enumerate(keys):
        conditions: list[dict[str, Any]] = [{k: {"_eq": v}} for k, v in zip(keys[:index], values[:index])]
        conditions.append({key: {"_gt": values[index]}})
        clauses.append(conditions[0] if len(conditions) == 1 else {"_and": conditions})
    if len(clauses) == 1:
        return clauses[0]
    return {"_and": [{keys[0]: {"_gte": values[0]}}, {"_or": clauses}]}


def _cursor_value(value: Any) -> Any:
    return str(value) if isinstance(value, Decimal) else value


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
            # Exclusive, as the shared SQL sources compare: an append sync would add the boundary
            # rows again otherwise. A date has no time part, so a later row can share the stored day.
            operator = "_gte" if field_type == IncrementalFieldType.Date else "_gt"
            base_where.append({incremental_field: {operator: format_watermark(watermark, field_type)}})
    else:
        keys = keyset

    if keys:
        order_by = [{key: "asc"} for key in keys]
        page_size = PAGE_SIZE
    else:
        if not table.orderable_columns:
            raise HasuraGraphQLError(
                f"{UNORDERED_TABLE_ERROR} {table.name}: it has no primary key and no column to order by. Add a primary key "
                "in your database, then sync again"
            )
        # Rows that tie on every orderable column can still swap places between pages.
        order_by = [{column: "asc"} for column in table.orderable_columns]
        page_size = OFFSET_PAGE_SIZE
    document = _page_document(table)

    position = manager.load_state() if manager.can_resume() else None
    if position is None or position.keys != keys:
        position = HasuraResumeConfig(keys=keys)

    while True:
        where = list(base_where)
        variables: dict[str, Any] = {"limit": page_size, "orderBy": order_by}
        if keys:
            if position.last_values is not None:
                where.append(_after(keys, position.last_values))
        else:
            variables["offset"] = position.offset
        if where:
            variables["where"] = where[0] if len(where) == 1 else {"_and": where}

        rows = client.fetch_page(table, document, variables)
        # Only an empty page ends the read: a page shorter than the limit can also come from a row
        # limit on the server, and stopping there would drop the rest of the table.
        if not rows:
            return

        if keys:
            # The resume state is JSON, so an exact decimal key travels as its string form.
            last_values = [_cursor_value(rows[-1].get(key)) for key in keys]
            if last_values == position.last_values:
                raise HasuraGraphQLError(f"Hasura returned the same page of {table.name} twice")
            position = HasuraResumeConfig(keys=keys, last_values=last_values)
        else:
            position = HasuraResumeConfig(keys=keys, offset=position.offset + len(rows))
        # Staged before the yield it covers, so a hand-off resumes after this page.
        manager.save_state(position)
        yield rows


def is_invalid_secret(error: BaseException) -> bool:
    if isinstance(error, HasuraAccessDeniedError):
        return True
    return isinstance(error, requests.HTTPError) and getattr(error.response, "status_code", None) == 401


def is_refused(error: BaseException) -> bool:
    return isinstance(error, requests.HTTPError) and getattr(error.response, "status_code", None) == 403
