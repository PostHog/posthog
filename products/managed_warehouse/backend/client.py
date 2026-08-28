from __future__ import annotations

import time
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg import sql as psql
from psycopg.conninfo import make_conninfo

from posthog.hogql.database.s3_table import (
    DUCKDB_SELF_MANAGED_SUPPORTED_FORMATS,
    S3Table,
    build_duckdb_azure_connection_string,
    parse_duckdb_azure_source,
    parse_duckdb_s3_source,
)

from products.managed_warehouse.backend.common import (
    get_duckgres_config_for_org,
    is_dev_mode,
    sanitize_ducklake_identifier,
)
from products.managed_warehouse.backend.facade.contracts import (
    DuckLakeAzureSecret,
    DuckLakeCompiledQuery,
    DuckLakeObjectStorageSecret,
    DuckLakeQueryResult,
    DuckLakeS3Secret,
    DuckLakeTableResult,
)
from products.managed_warehouse.backend.service_credentials import ServiceCredential
from products.managed_warehouse.backend.table_binding import bind_tables_to_ducklake

if TYPE_CHECKING:
    from posthog.schema import HogQLQuery

    from posthog.hogql.database.database import Database

    from posthog.models import User
    from posthog.models.team.team import Team

logger = logging.getLogger(__name__)


def make_duckgres_conninfo(
    team_id: int,
    *,
    organization_id: str | None = None,
    service_credential: ServiceCredential | None = None,
    application_name: str = "posthog",
) -> str:
    """Build a psycopg conninfo for a team's duckgres server.

    Default (no ``service_credential``): use the username/password from the
    stored ``DuckgresServer`` row. Materialization and internal warehouse
    helpers inherit the permissions of that login.

    With ``service_credential``: connect with a CP-issued, org-scoped
    per-credential grant (``svc_…`` credential_id + secret), short-lived and
    disposable. This is what background jobs (dagster) should present; see
    ``products/managed_warehouse/backend/service_credentials.py``.
    Host/port/database/sslmode come ENTIRELY from the credential's
    CP-issued ``connect`` block, so this branch is independent of the stored
    ``DuckgresServer`` row.
    Service credentials are only mintable for a provisioned production
    warehouse, so dev-mode is rejected rather than silently using the
    environment-configured login.

    ``application_name`` is forwarded to duckgres as a standard libpq startup
    param and echoed into its analytics events, so callers should pass a
    caller-identifying slug (e.g. ``"ducklake-register"``) instead of relying
    on the ``"posthog"`` default — that default only distinguishes PostHog's
    own connections in aggregate from customer clients (psql, their own
    application_name).
    """
    from products.managed_warehouse.backend.common import _duckgres_dev_config, _get_org_id_for_team

    if service_credential is not None:
        if is_dev_mode():
            raise RuntimeError(
                "service credentials are not available in dev mode (no CP to mint against); "
                "omit service_credential to use the dev duckgres defaults"
            )
        if not service_credential.credential_secret:
            raise RuntimeError("service_credential carries no secret; mint or refresh returned an invalid response")
        connect = service_credential.connect
        return make_conninfo(
            host=connect.host,
            port=connect.port,
            dbname=connect.database,
            user=service_credential.credential_id,
            password=service_credential.credential_secret,
            sslmode=connect.sslmode,
            sslcert="/tmp/no.txt",
            sslkey="/tmp/no.txt",
            sslrootcert="/tmp/no.txt",
            application_name=application_name,
        )

    if is_dev_mode():
        config = _duckgres_dev_config()
    else:
        org_id = organization_id or _get_org_id_for_team(team_id)
        config = get_duckgres_config_for_org(org_id)
    return make_conninfo(
        host=config["DUCKGRES_HOST"],
        port=int(config["DUCKGRES_PORT"]),
        dbname=config["DUCKGRES_DATABASE"],
        user=config["DUCKGRES_USERNAME"],
        password=config["DUCKGRES_PASSWORD"],
        sslmode="require",
        sslcert="/tmp/no.txt",
        sslkey="/tmp/no.txt",
        sslrootcert="/tmp/no.txt",
        application_name=application_name,
    )


# TODO: remove hardcoded schemas and derive the search path from the team's
# data warehouse sources / DAG configuration instead
_SEARCH_PATH_SCHEMAS = ["revenue", "stripe", "billing_public", "credit", "posthog"]


def _set_search_path(conn: psycopg.Connection[Any], extra_schemas: list[str] | None = None) -> None:
    schemas = (extra_schemas or []) + _SEARCH_PATH_SCHEMAS
    literal = psql.Literal(",".join(schemas))
    sql = psql.SQL("SET search_path TO {}").format(literal)
    conn.execute(sql)


def _object_storage_secrets_for_database(
    database: Database, referenced_table_ids: set[str]
) -> tuple[DuckLakeObjectStorageSecret, ...]:
    """Collect secrets for referenced self-managed tables in a built HogQL database.

    The referenced IDs come from tables printed through the access-control-pruned database.
    Reading credentials from the team's tables instead would let a restricted table's credentials
    serve an allowed one: DuckDB matches a secret on its ``s3://bucket/key`` scope alone, ignoring
    the endpoint, and breaks a scope tie by picking the lexicographically smaller secret name.
    """
    secrets: list[DuckLakeObjectStorageSecret] = []
    for table_name in database.get_warehouse_table_names():
        try:
            table = database.get_table(table_name)
        except Exception:
            continue
        # Connector-synced tables are rebound to their DuckLake copy and read no object storage.
        if (
            not isinstance(table, S3Table)
            or table.external_data_source_id
            or table.table_id is None
            or table.table_id not in referenced_table_ids
        ):
            continue
        if table.format not in DUCKDB_SELF_MANAGED_SUPPORTED_FORMATS or not table.access_key or not table.access_secret:
            continue
        name = f"self_managed_{str(table.table_id).replace('-', '')}"
        azure_source = parse_duckdb_azure_source(table.url)
        if azure_source is not None:
            connection_string = build_duckdb_azure_connection_string(
                azure_source,
                table.access_key,
                table.access_secret,
            )
            if connection_string is None:
                continue
            secrets.append(
                DuckLakeAzureSecret(
                    name=name,
                    connection_string=connection_string,
                    scope=azure_source.scope,
                )
            )
            continue

        s3_source = parse_duckdb_s3_source(table.url)
        if s3_source is not None:
            secrets.append(
                DuckLakeS3Secret(
                    name=name,
                    key_id=table.access_key,
                    secret=table.access_secret,
                    region=s3_source.region,
                    scope=s3_source.scope,
                    use_ssl=s3_source.use_ssl,
                    url_style=s3_source.url_style,
                    endpoint=s3_source.endpoint,
                )
            )
    return tuple(secrets)


def _configure_object_storage_secrets(
    conn: psycopg.Connection[Any], secrets: Sequence[DuckLakeObjectStorageSecret]
) -> None:
    if not secrets:
        return

    with conn.cursor() as cur:
        for secret in secrets:
            if isinstance(secret, DuckLakeS3Secret):
                secret_options = [
                    psql.SQL("TYPE S3"),
                    psql.SQL("KEY_ID %s"),
                    psql.SQL("SECRET %s"),
                    psql.SQL("REGION %s"),
                ]
                values: list[object] = [secret.key_id, secret.secret, secret.region]
                if secret.endpoint is not None:
                    secret_options.append(psql.SQL("ENDPOINT %s"))
                    values.append(secret.endpoint)
                secret_options.extend(
                    [
                        psql.SQL("USE_SSL %s"),
                        psql.SQL("URL_STYLE %s"),
                        psql.SQL("SCOPE %s"),
                    ]
                )
                values.extend([secret.use_ssl, secret.url_style, secret.scope])
            else:
                secret_options = [
                    psql.SQL("TYPE AZURE"),
                    psql.SQL("CONNECTION_STRING %s"),
                    psql.SQL("SCOPE %s"),
                ]
                values = [secret.connection_string, secret.scope]
            statement = psql.SQL("CREATE OR REPLACE TEMPORARY SECRET {} ({})").format(
                psql.Identifier(secret.name),
                psql.SQL(", ").join(secret_options),
            )
            try:
                cur.execute(statement, values)
                # DuckDB keeps secrets in the transaction that created them, so hold each one
                # on its own: sharing a transaction would let the rollback below discard every
                # secret installed before the rejected one.
                conn.commit()
            except Exception:
                # A secret duckgres rejects only breaks the table it belongs to, so keep going
                # and let the query fail on that table instead of on every other one too.
                conn.rollback()
                logger.warning("Could not configure DuckLake object storage access for %s", secret.name, exc_info=True)


def compile_hogql_to_ducklake_sql(
    team_id: int,
    query: HogQLQuery,
    *,
    team: Team | None = None,
    user: User | None = None,
    bypass_warehouse_access_control: bool = False,
) -> DuckLakeCompiledQuery:
    """Compile a HogQLQuery to DuckDB-dialect SQL for DuckLake.

    The returned ``values`` hold parameter bindings for ``psycopg``'s ``%(name)s``
    placeholders embedded in ``sql``; callers must pass them to
    ``cursor.execute(sql, values)`` or the query will fail with an
    unbound-placeholder error. ``object_storage_secrets`` must be installed on the
    connection before the query runs, or its self-managed tables cannot be read.
    """
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.database.database import Database
    from posthog.hogql.parser import parse_select
    from posthog.hogql.printer.utils import prepare_and_print_ast
    from posthog.hogql.variables import replace_variables

    from posthog.models.team.team import Team

    parsed = parse_select(query.query)
    if query.variables:
        team = team or Team.objects.get(pk=team_id)
        parsed = replace_variables(parsed, list(query.variables.values()), team)
    # Build the database up front so warehouse tables can be bound from the ClickHouse
    # S3 table function to their DuckLake-materialized tables before printing.
    database = Database.create_for(
        team_id,
        user=user,
        bypass_warehouse_access_control=bypass_warehouse_access_control,
    )
    bind_tables_to_ducklake(database, team_id)
    # Separate context for the DuckDB print — the HogQL round-trip below shouldn't
    # contribute to ``postgres_context.values``.
    postgres_context = HogQLContext(
        team_id=team_id,
        user=user,
        enable_select_queries=True,
        bypass_warehouse_access_control=bypass_warehouse_access_control,
        database=database,
    )
    postgres_sql, _ = prepare_and_print_ast(parsed, postgres_context, dialect="duckdb")

    hogql_context = HogQLContext(
        team_id=team_id,
        user=user,
        enable_select_queries=True,
        bypass_warehouse_access_control=bypass_warehouse_access_control,
    )
    hogql_pretty, _ = prepare_and_print_ast(parsed, hogql_context, dialect="hogql")

    return DuckLakeCompiledQuery(
        sql=postgres_sql,
        values=dict(postgres_context.values),
        hogql=hogql_pretty,
        object_storage_secrets=_object_storage_secrets_for_database(
            database, postgres_context.referenced_self_managed_table_ids
        ),
    )


def execute_ducklake_query(
    team_id: int,
    *,
    sql: str | None = None,
    query: HogQLQuery | None = None,
    organization_id: str | None = None,
    team: Team | None = None,
    user: User | None = None,
    bypass_warehouse_access_control: bool = False,
) -> DuckLakeQueryResult:
    """Execute a query against a team's duckgres server.

    Accepts either raw SQL or a HogQLQuery (which gets compiled to
    DuckDB-dialect SQL). Exactly one of `sql` or `query` must be provided.

    Pass organization_id to skip the Team→Organization lookup when org
    context is already available from the caller. Pass team to skip the
    Team lookup used for variable substitution. Pass user so HogQL compilation
    resolves data warehouse access control the same way as normal query execution.
    Set bypass_warehouse_access_control only from trusted internal callers that
    must compile without a user, such as materialization.

    Only the `query` form can read self-managed object storage — raw `sql` carries no
    compiled schema, so no object storage secrets are installed for it.
    """
    if sql and query:
        raise ValueError("Provide either sql or query, not both")
    if not sql and not query:
        raise ValueError("Provide either sql or query")

    hogql_pretty: str | None = None
    values: dict[str, object] = {}
    object_storage_secrets: Sequence[DuckLakeObjectStorageSecret] = ()
    if query:
        compiled = compile_hogql_to_ducklake_sql(
            team_id,
            query,
            team=team,
            user=user,
            bypass_warehouse_access_control=bypass_warehouse_access_control,
        )
        sql = compiled.sql
        values = compiled.values
        hogql_pretty = compiled.hogql
        object_storage_secrets = compiled.object_storage_secrets

    assert sql is not None

    conninfo = make_duckgres_conninfo(team_id, organization_id=organization_id, application_name="endpoints-shadow")
    _connect_start = time.monotonic()
    with psycopg.connect(conninfo) as conn:
        connect_ms = (time.monotonic() - _connect_start) * 1000
        _configure_object_storage_secrets(conn, object_storage_secrets)
        _set_search_path(conn)
        with conn.cursor() as cur:
            _query_start = time.monotonic()
            cur.execute(sql, values or None)
            columns = [desc.name for desc in cur.description] if cur.description else []
            types = [str(desc.type_code) for desc in cur.description] if cur.description else []
            rows = cur.fetchall()
            query_ms = (time.monotonic() - _query_start) * 1000
    return DuckLakeQueryResult(
        columns=columns,
        types=types,
        results=[list(r) for r in rows],
        sql=sql,
        hogql=hogql_pretty,
        connect_ms=connect_ms,
        query_ms=query_ms,
    )


def _calculate_table_size(conninfo: str, safe_schema: str, safe_table: str) -> int:
    try:
        with psycopg.connect(conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.file_size_bytes
                    FROM ducklake_table_info('ducklake') t
                    JOIN __ducklake_metadata_ducklake.ducklake_schema s
                    ON t.schema_id = s.schema_id AND s.end_snapshot IS NULL
                    WHERE s.schema_name = %s AND t.table_name = %s
                    """,
                    (safe_schema, safe_table),
                )
                row = cur.fetchone()
                return int(row[0]) if row and row[0] else 0
    except Exception:
        return 0


def execute_ducklake_create_table(
    team_id: int,
    sql: str,
    schema_name: str,
    table_name: str,
    values: dict[str, object] | None = None,
    *,
    organization_id: str | None = None,
    object_storage_secrets: Sequence[DuckLakeObjectStorageSecret] = (),
) -> DuckLakeTableResult:
    """Execute a query via duckgres and materialize the result as a DuckLake table.

    Creates or replaces a table in the given schema using CREATE OR REPLACE TABLE ... AS.
    The table is stored natively in DuckLake (Parquet on S3 + Postgres catalog metadata).

    Pass organization_id to skip the Team→Organization lookup when org
    context is already available from the caller.

    ``values`` carries parameter bindings for any ``%(name)s`` placeholders in ``sql``
    (as produced by ``compile_hogql_to_ducklake_sql``). It is passed through to
    ``psycopg`` so the SELECT body is executed with safe parameter binding. Pass that
    same compilation's ``object_storage_secrets`` so the SELECT can read self-managed object storage.
    """
    safe_schema = sanitize_ducklake_identifier(schema_name, default_prefix="shadow")
    safe_table = sanitize_ducklake_identifier(table_name, default_prefix="model")
    qualified = psql.Identifier(safe_schema, safe_table)
    conninfo = make_duckgres_conninfo(team_id, organization_id=organization_id, application_name="materialization")
    # capture previous table size before replacing — best-effort, don't block materialization
    previous_file_size_bytes = _calculate_table_size(conninfo, safe_schema, safe_table)
    with psycopg.connect(conninfo) as conn:
        _configure_object_storage_secrets(conn, object_storage_secrets)
        conn.execute(psql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(psql.Identifier(safe_schema)))
        # duckgres SET seems to only accept a single comma-separated string value with single quotes
        _set_search_path(conn, extra_schemas=[safe_schema])
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL("""
                    CREATE OR REPLACE TABLE {} AS (
                        {}
                    )
                """).format(qualified, psql.SQL(sql)),
                values or None,
            )
    row_count = 0
    try:
        with psycopg.connect(conninfo) as conn:
            _set_search_path(conn, extra_schemas=[safe_schema])
            with conn.cursor() as cur:
                cur.execute(psql.SQL("SELECT count(*) FROM {}").format(qualified))
                row = cur.fetchone()
                row_count = int(row[0]) if row else 0
    except Exception:
        pass
    # capture new table size — best-effort, don't block materialization
    file_size_bytes = _calculate_table_size(conninfo, safe_schema, safe_table)
    return DuckLakeTableResult(
        schema_name=safe_schema,
        table_name=safe_table,
        row_count=row_count,
        file_size_bytes=file_size_bytes,
        file_size_delta_bytes=file_size_bytes - previous_file_size_bytes,
    )
