import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from llm_gateway.db.required_tables import REQUIRED_TABLES
from llm_gateway.metrics.prometheus import DB_POOL_EXHAUSTED

POOL_ACQUIRE_TIMEOUT = 5.0

# An absent relation is excluded (to_regclass NULL, COALESCE TRUE): schema
# absence is a different failure than a revoked grant.
MISSING_PRIVILEGES_QUERY = """
    SELECT t.table_name
    FROM unnest($1::text[]) AS t(table_name)
    WHERE NOT COALESCE(has_table_privilege(current_user, to_regclass(t.table_name), 'SELECT'), TRUE)
"""


async def missing_table_privileges(conn: asyncpg.Connection) -> list[str]:
    """Return the REQUIRED_TABLES the connected role cannot SELECT from."""
    rows = await conn.fetch(MISSING_PRIVILEGES_QUERY, sorted(REQUIRED_TABLES))
    return [row["table_name"] for row in rows]


async def init_db_pool(database_url: str, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        server_settings={"application_name": "llm-gateway"},
    )


async def close_db_pool(pool: asyncpg.Pool) -> None:
    await pool.close()


@asynccontextmanager
async def acquire_connection(pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Connection]:
    """Acquire a connection with timeout, tracking exhaustion events."""
    try:
        async with asyncio.timeout(POOL_ACQUIRE_TIMEOUT):
            conn = await pool.acquire()
    except (TimeoutError, asyncpg.exceptions.TooManyConnectionsError):
        DB_POOL_EXHAUSTED.inc()
        raise
    try:
        yield conn
    finally:
        await pool.release(conn)
