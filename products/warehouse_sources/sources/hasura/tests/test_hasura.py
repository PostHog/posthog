import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.sources.hasura._config import HasuraSourceConfig
from products.warehouse_sources.sources.hasura.hasura import (
    HasuraConfigError,
    HasuraGraphQLError,
    HasuraRequestError,
    HasuraResumeConfig,
    HasuraTimeoutError,
    resolve_graphql_url,
)
from products.warehouse_sources.sources.hasura.source import INVALID_SECRET_MESSAGE, REFUSED_MESSAGE, HasuraSource
from products.warehouse_sources.sources.sdk import UNRESOLVED_HOST_REASON, TemporaryHostResolutionError
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)

MODULE = "products.warehouse_sources.sources.hasura.hasura"
# The query string stands in for a gateway key, which error messages must not repeat.
CONFIG = HasuraSourceConfig(
    graphql_url="https://acme.hasura.app/v1/graphql?apikey=gateway-key", admin_secret="adm1n-s3cret"
)
# Hasura v2.48.5 answered a wrong admin secret with this body, at HTTP 200.
ACCESS_DENIED_BODY = {
    "errors": [
        {
            "message": 'invalid "x-hasura-admin-secret"/"x-hasura-access-key"',
            "extensions": {"path": "$", "code": "access-denied"},
        }
    ]
}


@pytest.fixture(autouse=True)
def _allow_test_host() -> Iterator[None]:
    # `is_url_allowed` resolves DNS outside dev mode; the hosts here are fake.
    with mock.patch(f"{MODULE}.is_url_allowed", return_value=(True, None)):
        yield


def _ref(kind: str, name: str | None = None, of: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"kind": kind, "name": name, "ofType": of}


def _scalar(name: str, required: bool = False) -> dict[str, Any]:
    ref = _ref("SCALAR", name)
    return _ref("NON_NULL", of=ref) if required else ref


def _list_of(type_name: str) -> dict[str, Any]:
    return _ref("NON_NULL", of=_ref("LIST", of=_ref("NON_NULL", of=_ref("OBJECT", type_name))))


def _arg(name: str, type_ref: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "type": type_ref}


def _table_args(type_name: str) -> list[dict[str, Any]]:
    return [
        _arg("distinct_on", _ref("LIST", of=_ref("NON_NULL", of=_ref("ENUM", f"{type_name}_select_column")))),
        _arg("limit", _scalar("Int")),
        _arg("offset", _scalar("Int")),
        _arg("order_by", _ref("LIST", of=_ref("NON_NULL", of=_ref("INPUT_OBJECT", f"{type_name}_order_by")))),
        _arg("where", _ref("INPUT_OBJECT", f"{type_name}_bool_exp")),
    ]


def _object(name: str, columns: dict[str, dict[str, Any]], extra: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    fields = [{"name": column, "args": [], "type": type_ref} for column, type_ref in columns.items()]
    return {"kind": "OBJECT", "name": name, "fields": fields + (extra or []), "inputFields": None}


def _order_by(name: str, columns: list[str], relationships: list[str] | None = None) -> dict[str, Any]:
    inputs = [{"name": column, "type": _ref("ENUM", "order_by")} for column in columns]
    inputs += [{"name": rel, "type": _ref("INPUT_OBJECT", "other_order_by")} for rel in relationships or []]
    return {"kind": "INPUT_OBJECT", "name": f"{name}_order_by", "fields": None, "inputFields": inputs}


def _by_pk(name: str, type_name: str, keys: dict[str, str]) -> dict[str, Any]:
    args = [_arg(key, _scalar(scalar, required=True)) for key, scalar in keys.items()]
    return {"name": name, "args": args, "type": _ref("OBJECT", type_name)}


def _types() -> list[dict[str, Any]]:
    # The introspection types Hasura v2 answers with, one per discovery edge case.
    orders = _object(
        "orders",
        {
            "id": _scalar("Int", required=True),
            "customer": _scalar("String"),
            "total": _scalar("numeric"),
            "meta": _scalar("jsonb"),
            "status": _ref("ENUM", "order_status"),
            "created_at": _scalar("timestamptz"),
            "updated_at": _scalar("timestamptz"),
            "legacy_at": _scalar("datetime"),
            "ship_date": _scalar("date"),
        },
        extra=[
            # An object relationship, an array relationship and a computed field that needs an argument.
            {"name": "account", "args": [], "type": _ref("OBJECT", "accounts")},
            {"name": "items", "args": _table_args("line_items"), "type": _list_of("line_items")},
            {
                "name": "discounted_total",
                "args": [_arg("args", _ref("NON_NULL", of=_ref("INPUT_OBJECT", "discount_args")))],
                "type": _scalar("numeric"),
            },
        ],
    )
    root_fields = [
        {"name": "orders", "args": _table_args("orders"), "type": _list_of("orders")},
        {"name": "orders_aggregate", "args": _table_args("orders"), "type": _ref("OBJECT", "orders_aggregate")},
        _by_pk("orders_by_pk", "orders", {"id": "Int"}),
        {"name": "line_items", "args": _table_args("line_items"), "type": _list_of("line_items")},
        _by_pk("line_items_by_pk", "line_items", {"order_id": "Int", "line_no": "Int"}),
        # A key column that references an enum table has no `_gt`, so it can't carry a keyset.
        {"name": "user_roles", "args": _table_args("user_roles"), "type": _list_of("user_roles")},
        {
            "name": "user_roles_by_pk",
            "args": [
                _arg("user_id", _scalar("Int", required=True)),
                _arg("role", _ref("NON_NULL", of=_ref("ENUM", "roles_enum"))),
            ],
            "type": _ref("OBJECT", "user_roles"),
        },
        {"name": "order_totals", "args": _table_args("order_totals"), "type": _list_of("order_totals")},
        {"name": "raw_blobs", "args": _table_args("raw_blobs"), "type": _list_of("raw_blobs")},
        # Custom root field names: no `_by_pk` suffix to find the key by.
        {"name": "allAccounts", "args": _table_args("accounts"), "type": _list_of("accounts")},
        _by_pk("accountById", "accounts", {"id": "uuid"}),
        # A tracked function that needs arguments, and an action with no table arguments.
        {
            "name": "search_orders",
            "args": [_arg("args", _ref("NON_NULL", of=_ref("INPUT_OBJECT", "search_args"))), *_table_args("orders")],
            "type": _list_of("orders"),
        },
        {"name": "recentOrders", "args": [], "type": _list_of("orders")},
    ]
    return [
        {"kind": "OBJECT", "name": "query_root", "fields": root_fields, "inputFields": None},
        orders,
        _object(
            "line_items",
            {
                "order_id": _scalar("Int", required=True),
                "line_no": _scalar("Int", required=True),
                "sku": _scalar("String"),
            },
        ),
        _object(
            "user_roles",
            {"user_id": _scalar("Int", required=True), "role": _ref("NON_NULL", of=_ref("ENUM", "roles_enum"))},
        ),
        _object("order_totals", {"customer": _scalar("String"), "total": _scalar("numeric")}),
        _object("raw_blobs", {"payload": _scalar("json")}),
        _object("accounts", {"id": _scalar("uuid", required=True), "name": _scalar("String")}),
        _order_by(
            "orders",
            ["id", "customer", "total", "meta", "status", "created_at", "updated_at", "legacy_at", "ship_date"],
            ["account"],
        ),
        _order_by("line_items", ["order_id", "line_no", "sku"]),
        _order_by("user_roles", ["user_id", "role"]),
        _order_by("order_totals", ["customer", "total"]),
        _order_by("raw_blobs", []),
        _order_by("accounts", ["id", "name"]),
    ]


def _introspection_answer(request: RecordedRequest) -> ScriptedResponse | None:
    body = request.json()
    query = body["query"]
    types = {t["name"]: t for t in _types()}
    if "PostHogHasuraRootFields" in query:
        return ScriptedResponse(json={"data": {"__schema": {"queryType": types["query_root"]}}})
    if "PostHogHasuraTableTypes" in query:
        variables = body["variables"]
        return ScriptedResponse(
            json={"data": {"object": types.get(variables["object"]), "orderBy": types.get(variables["orderBy"])}}
        )
    if "__schema" in query:
        return ScriptedResponse(json={"data": {"__schema": {"queryType": {"name": "query_root"}, "types": _types()}}})
    return None


def _comparable(value: Any) -> Any:
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}T", value):
        return datetime.fromisoformat(value)
    return value


def _matches(row: dict[str, Any], where: dict[str, Any]) -> bool:
    for key, condition in where.items():
        if key == "_and":
            if not all(_matches(row, clause) for clause in condition):
                return False
        elif key == "_or":
            if not any(_matches(row, clause) for clause in condition):
                return False
        else:
            value = _comparable(row.get(key))
            for op, target in condition.items():
                target = _comparable(target)
                if op == "_is_null":
                    ok = (value is None) == target
                elif value is None:
                    ok = False
                else:
                    ok = {"_eq": value == target, "_gt": value > target, "_gte": value >= target}[op]
                if not ok:
                    return False
    return True


class FakeHasura:
    # Answers introspection, and page queries from in-memory rows with where, order_by, limit and offset.
    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self.tables = tables
        self.page_variables: list[dict[str, Any]] = []

    def __call__(self, request: RecordedRequest) -> ScriptedResponse:
        introspection = _introspection_answer(request)
        if introspection is not None:
            return introspection
        body = request.json()
        table = re.search(r"\{ (\w+)\(limit:", body["query"])
        assert table is not None, body["query"]
        variables = body["variables"]
        self.page_variables.append(variables)
        rows = [row for row in self.tables[table.group(1)] if _matches(row, variables.get("where") or {})]
        for clause in reversed(variables["orderBy"]):
            ((column, _),) = clause.items()
            rows.sort(key=lambda row: (row.get(column) is None, _comparable(row.get(column))))
        offset = variables.get("offset") or 0
        return ScriptedResponse(json={"data": {table.group(1): rows[offset : offset + variables["limit"]]}})


def _orders(count: int) -> list[dict[str, Any]]:
    return [
        {
            "id": i,
            "customer": f"c{i % 3}",
            "total": i,
            "meta": {"n": i},
            "status": "OPEN",
            "created_at": f"2024-01-{i:02d}T00:00:00+00:00",
            # Descending in id, so an incremental read orders differently from a full refresh.
            "updated_at": f"2024-02-{count + 1 - i:02d}T12:00:00+00:00",
            "legacy_at": f"2024-04-{i:02d}T00:00:00.123Z",
            "ship_date": f"2024-03-{i:02d}",
        }
        for i in range(1, count + 1)
    ]


def _driver() -> SourceDriver:
    return SourceDriver(HasuraSource(), CONFIG)


def test_get_schemas_discovers_tables_keys_and_incremental_columns() -> None:
    with scripted_network(FakeHasura({})):
        schemas = {schema.name: schema for schema in HasuraSource().get_schemas(CONFIG, team_id=1)}

    # Aggregates, `_by_pk` lookups, functions with required args and actions are not tables.
    assert set(schemas) == {"orders", "line_items", "user_roles", "order_totals", "raw_blobs", "allAccounts"}
    orders = schemas["orders"]
    # Relationships and a computed field that needs an argument are not columns.
    assert [column[0] for column in orders.columns] == [
        "id",
        "customer",
        "total",
        "meta",
        "status",
        "created_at",
        "updated_at",
        "legacy_at",
        "ship_date",
    ]
    assert orders.detected_primary_keys == ["id"]
    # `datetime` (legacy_at) is SQL Server's or BigQuery's, which differ in precision, so it is not offered.
    assert {field["field"]: field["type"] for field in orders.incremental_fields} == {
        "id": "integer",
        "created_at": "datetime",
        "updated_at": "datetime",
        "ship_date": "date",
    }
    assert orders.supports_incremental and orders.supports_append
    assert schemas["line_items"].detected_primary_keys == ["order_id", "line_no"]
    # The key comes from the single custom root field that looks a row up by required column args.
    assert schemas["allAccounts"].detected_primary_keys == ["id"]
    # A view, and a key with an enum column, can only be fully refreshed.
    for name in ("order_totals", "user_roles"):
        schema = schemas[name]
        assert schema.detected_primary_keys is None
        assert not schema.supports_incremental and not schema.supports_append and schema.incremental_fields == []


@pytest.mark.parametrize("names", [["orders", "allAccounts", "user_roles", "missing"], ["line_items"]])
def test_get_schemas_for_named_tables_matches_the_full_introspection(names: list[str]) -> None:
    with scripted_network(FakeHasura({})):
        full = {schema.name: schema for schema in HasuraSource().get_schemas(CONFIG, team_id=1)}
    with scripted_network(FakeHasura({})) as network:
        named = HasuraSource().get_schemas(CONFIG, team_id=1, names=names)

    assert {schema.name: schema for schema in named} == {name: full[name] for name in names if name in full}
    assert not any("PostHogHasuraIntrospection" in str(request.json()) for request in network.requests_log)


def _schema_with_root(root_fields: list[dict[str, Any]], extra_types: list[dict[str, Any]]) -> dict[str, Any]:
    query_root = {"kind": "OBJECT", "name": "query_root", "fields": root_fields, "inputFields": None}
    return {"data": {"__schema": {"queryType": {"name": "query_root"}, "types": [query_root, *extra_types]}}}


@pytest.mark.parametrize(
    ("schema", "expected_message"),
    [
        (
            _schema_with_root(
                [{"name": "mydb", "args": [], "type": _ref("NON_NULL", of=_ref("OBJECT", "mydb_query"))}],
                [
                    {
                        "kind": "OBJECT",
                        "name": "mydb_query",
                        "fields": [{"name": "orders", "args": _table_args("orders"), "type": _list_of("orders")}],
                        "inputFields": None,
                    }
                ],
            ),
            "Hasura puts its root fields under a namespace (mydb)",
        ),
        (
            _schema_with_root(
                [
                    {
                        "name": "orders",
                        "args": [
                            _arg("limit", _scalar("Int")),
                            _arg("orderBy", _ref("LIST", of=_ref("INPUT_OBJECT", "x"))),
                        ],
                        "type": _list_of("orders"),
                    }
                ],
                [],
            ),
            "Hasura uses the graphql-default naming convention",
        ),
    ],
)
def test_get_schemas_explains_sources_it_cannot_read(schema: dict[str, Any], expected_message: str) -> None:
    with scripted_network(always(ScriptedResponse(json=schema))):
        with pytest.raises(HasuraGraphQLError, match=re.escape(expected_message)):
            HasuraSource().get_schemas(CONFIG, team_id=1)


@pytest.mark.parametrize(
    ("failure", "expected_error", "resent"),
    [
        (
            requests.ConnectionError("Max retries exceeded with url: /v1/graphql?apikey=gateway-key"),
            HasuraRequestError,
            True,
        ),
        # The database can still be running a slow query, so a read timeout is not sent again at once.
        (requests.ReadTimeout("Read timed out. url: /v1/graphql?apikey=gateway-key"), HasuraTimeoutError, False),
    ],
)
def test_request_failures_hide_the_query_string(
    failure: Exception, expected_error: type[Exception], resent: bool
) -> None:
    result = _driver().run("orders", always(failure), should_use_incremental_field=False)

    assert isinstance(result.raised, expected_error)
    assert "gateway-key" not in str(result.raised) and result.raised.__suppress_context__
    assert (len(result.requests) > 1) is resent


def test_full_refresh_walks_keyset_pages_until_an_empty_page() -> None:
    fake = FakeHasura({"orders": _orders(5)})

    with mock.patch(f"{MODULE}.PAGE_SIZE", 2):
        result = _driver().run("orders", fake, should_use_incremental_field=False)

    assert result.raised is None
    assert [row["id"] for row in result.rows] == [1, 2, 3, 4, 5]
    # A short page does not end the read, because a server row limit can also make one.
    assert [variables.get("where") for variables in fake.page_variables] == [
        None,
        {"id": {"_gt": 2}},
        {"id": {"_gt": 4}},
        {"id": {"_gt": 5}},
    ]
    assert all(variables["orderBy"] == [{"id": "asc"}] for variables in fake.page_variables)
    assert result.response is not None
    assert result.response.primary_keys == ["id"] and result.response.sort_mode is None
    assert result.committed_states[-1] == HasuraResumeConfig(keys=["id"], last_values=[5])
    # A sync introspects only its own table, not every type of the schema.
    assert "PostHogHasuraIntrospection" not in str(result.requests[0].json())
    # The admin secret rides in a header, so it must be redacted and never follow a redirect.
    assert result.requests[0].headers["x-hasura-admin-secret"] == "adm1n-s3cret"
    assert result.session_options[0]["redact_values"] == ("adm1n-s3cret",)
    assert result.session_options[0]["allow_redirects"] is False


@pytest.mark.parametrize(
    ("incremental_field", "watermark", "expected_bound", "expected_ids"),
    [
        ("updated_at", None, None, [5, 4, 3, 2, 1]),
        ("updated_at", datetime(2024, 2, 3, 12, tzinfo=UTC), {"_gt": "2024-02-03T12:00:00.000000Z"}, [2, 1]),
        ("id", 4, {"_gt": 4}, [5]),
        # A later row can share the stored day, so a date bound stays inclusive.
        ("ship_date", date(2024, 3, 2), {"_gte": "2024-03-02"}, [2, 3, 4, 5]),
    ],
)
def test_incremental_read_filters_on_the_watermark_and_orders_by_the_field(
    incremental_field: str, watermark: Any, expected_bound: dict[str, Any] | None, expected_ids: list[int]
) -> None:
    fake = FakeHasura({"orders": _orders(5)})

    result = _driver().run(
        "orders", fake, incremental_field=incremental_field, db_incremental_field_last_value=watermark
    )

    assert result.raised is None
    assert [row["id"] for row in result.rows] == expected_ids
    first = fake.page_variables[0]
    expected_where: list[dict[str, Any]] = [{incremental_field: {"_is_null": False}}]
    if expected_bound is not None:
        expected_where.append({incremental_field: expected_bound})
    assert first.get("where") == (expected_where[0] if len(expected_where) == 1 else {"_and": expected_where})
    # The key breaks ties, and an incremental column that is the key is not ordered twice.
    expected_order = [{incremental_field: "asc"}] + ([] if incremental_field == "id" else [{"id": "asc"}])
    assert first["orderBy"] == expected_order
    assert result.response is not None and result.response.sort_mode == "asc"


def test_incremental_keyset_continues_after_ties_with_a_range_bound() -> None:
    rows = [{**row, "updated_at": "2024-02-01T00:00:00+00:00"} for row in _orders(3)]
    fake = FakeHasura({"orders": rows})

    with mock.patch(f"{MODULE}.PAGE_SIZE", 2):
        result = _driver().run("orders", fake, incremental_field="updated_at")

    assert [row["id"] for row in result.rows] == [1, 2, 3]
    tie = "2024-02-01T00:00:00+00:00"
    # The leading `_gte` lets the database seek to the last row read instead of scanning past it.
    assert fake.page_variables[1]["where"] == {
        "_and": [
            {"updated_at": {"_is_null": False}},
            {
                "_and": [
                    {"updated_at": {"_gte": tie}},
                    {
                        "_or": [
                            {"updated_at": {"_gt": tie}},
                            {"_and": [{"updated_at": {"_eq": tie}}, {"id": {"_gt": 2}}]},
                        ]
                    },
                ]
            },
        ]
    }


@pytest.mark.parametrize(
    ("schema_name", "rows"),
    [
        ("order_totals", [{"customer": f"c{i}", "total": i} for i in range(4)]),
        ("user_roles", [{"user_id": i // 2, "role": ("ADMIN", "USER")[i % 2]} for i in range(4)]),
    ],
)
def test_tables_without_a_usable_key_page_by_offset(schema_name: str, rows: list[dict[str, Any]]) -> None:
    fake = FakeHasura({schema_name: rows})

    with mock.patch(f"{MODULE}.OFFSET_PAGE_SIZE", 3):
        result = _driver().run(schema_name, fake, should_use_incremental_field=False)

    assert result.raised is None
    assert len(result.rows) == len(rows)
    assert [variables.get("offset") for variables in fake.page_variables] == [0, 3, 4]
    assert all("where" not in variables for variables in fake.page_variables)


def test_decimal_columns_keep_every_digit_and_json_columns_stay_plain() -> None:
    page = (
        b'{"data": {"orders": [{"id": 1, "total": 12345678901234567890.123456789012345678, "meta": {"ratio": 0.5}},'
        b' {"id": 2, "total": 7, "meta": null}]}}'
    )
    answers = iter([ScriptedResponse(body=page), ScriptedResponse(json={"data": {"orders": []}})])

    def respond(request: RecordedRequest) -> ScriptedResponse:
        return _introspection_answer(request) or next(answers)

    result = _driver().run("orders", respond, should_use_incremental_field=False)

    assert result.raised is None
    assert result.rows[0]["total"] == Decimal("12345678901234567890.123456789012345678")
    assert result.rows[1]["total"] == Decimal(7)
    # A Decimal inside a json value would not serialize, so json columns keep the plain decode.
    assert result.rows[0]["meta"] == {"ratio": 0.5} and isinstance(result.rows[0]["meta"]["ratio"], float)


@pytest.mark.parametrize(
    ("resume_state", "expected_first_where"),
    [
        (HasuraResumeConfig(keys=["id"], last_values=[3]), {"id": {"_gt": 3}}),
        # A cursor saved under other keys (the user switched to incremental) is not reused.
        (HasuraResumeConfig(keys=["updated_at", "id"], last_values=["2024-02-01T12:00:00+00:00", 5]), None),
    ],
)
def test_resume_continues_from_a_matching_cursor_only(
    resume_state: HasuraResumeConfig, expected_first_where: dict[str, Any] | None
) -> None:
    fake = FakeHasura({"orders": _orders(5)})

    result = _driver().run("orders", fake, should_use_incremental_field=False, resume_state=resume_state)

    assert result.raised is None
    assert fake.page_variables[0].get("where") == expected_first_where


@pytest.mark.parametrize(
    ("schema_name", "incremental_field", "answer", "expected_error", "expected_message"),
    [
        ("missing", None, None, ValueError, "doesn't expose the table missing"),
        ("orders", "customer", None, HasuraGraphQLError, "can't sync this table incrementally on customer"),
        ("raw_blobs", None, None, HasuraGraphQLError, "can't page through the table raw_blobs"),
        (
            "orders",
            None,
            ScriptedResponse(
                json={
                    "errors": [
                        {
                            "message": "database query error",
                            "extensions": {
                                "path": "$",
                                "code": "unexpected",
                                "internal": {
                                    "error": {
                                        "message": "canceling statement due to statement timeout",
                                        "status_code": "57014",
                                    }
                                },
                            },
                        }
                    ]
                }
            ),
            HasuraGraphQLError,
            "database query error: canceling statement due to statement timeout",
        ),
        (
            "orders",
            None,
            ScriptedResponse(json={"data": {"orders": [{"id": 1}]}}),
            HasuraGraphQLError,
            "same page of orders twice",
        ),
        (
            "orders",
            None,
            ScriptedResponse(body=b"<html>gateway</html>"),
            HasuraGraphQLError,
            "https://acme.hasura.app/v1/graphql did not answer with a GraphQL response",
        ),
    ],
)
def test_extraction_errors(
    schema_name: str,
    incremental_field: str | None,
    answer: ScriptedResponse | None,
    expected_error: type[Exception],
    expected_message: str,
) -> None:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        introspection = _introspection_answer(request)
        if introspection is not None:
            return introspection
        assert answer is not None
        return answer

    result = _driver().run(schema_name, respond, incremental_field=incremental_field)

    assert isinstance(result.raised, expected_error)
    assert expected_message in str(result.raised)
    assert "gateway-key" not in str(result.raised)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (ScriptedResponse(json={"data": {"__schema": {"queryType": {"name": "query_root"}}}}), (True, None)),
        (ScriptedResponse(json=ACCESS_DENIED_BODY), (False, INVALID_SECRET_MESSAGE)),
        (ScriptedResponse(status=401), (False, INVALID_SECRET_MESSAGE)),
        (ScriptedResponse(status=403), (False, REFUSED_MESSAGE)),
        (requests.ConnectionError("refused"), (False, "Could not reach a Hasura GraphQL API")),
    ],
)
def test_validate_credentials(answer: Any, expected: tuple[bool, str | None]) -> None:
    with scripted_network(always(answer)) as network:
        valid, message = HasuraSource().validate_credentials(CONFIG, team_id=1)

    assert valid is expected[0]
    assert (message is None) if expected[1] is None else (expected[1] in (message or ""))
    # The probe fails fast in the wizard: one request, no retry.
    assert len(network.requests_log) == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("acme.hasura.app", "https://acme.hasura.app/v1/graphql"),
        (" https://acme.hasura.app/ ", "https://acme.hasura.app/v1/graphql"),
        ("https://api.example.com/hasura/v1/graphql", "https://api.example.com/hasura/v1/graphql"),
        ("https://api.example.com:8443/v1/graphql#frag", "https://api.example.com:8443/v1/graphql"),
    ],
)
def test_resolve_graphql_url_normalizes_the_endpoint(raw: str, expected: str) -> None:
    assert resolve_graphql_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "verdict", "expected_error", "expected_message"),
    [
        ("", (True, None), HasuraConfigError, "Enter the URL"),
        ("http://acme.hasura.app/v1/graphql", (True, None), HasuraConfigError, "must be an https URL"),
        ("https://user:pw@acme.hasura.app/v1/graphql", (True, None), HasuraConfigError, "Remove the user name"),
        ("https://10.0.0.5/v1/graphql", (False, "private IP"), HasuraConfigError, "this Hasura URL: private IP"),
        # A DNS blip is not a policy decision, so a sync retries it.
        (
            "https://acme.hasura.app/v1/graphql",
            (False, UNRESOLVED_HOST_REASON),
            TemporaryHostResolutionError,
            "acme.hasura.app",
        ),
    ],
)
def test_unsafe_endpoints_fail_before_the_secret_is_sent(
    raw: str, verdict: tuple[bool, str | None], expected_error: type[Exception], expected_message: str
) -> None:
    with (
        mock.patch(f"{MODULE}.is_url_allowed", return_value=verdict),
        scripted_network(always(ScriptedResponse(json={"data": {}}))) as network,
    ):
        with pytest.raises(expected_error, match=re.escape(expected_message)):
            resolve_graphql_url(raw)
        valid, _ = HasuraSource().validate_credentials(
            HasuraSourceConfig(graphql_url=raw, admin_secret="secret"), team_id=1
        )

    assert valid is False
    assert network.requests_log == []
