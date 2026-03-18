import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from llm_gateway.metrics.prometheus import DB_POOL_EXHAUSTED

POOL_ACQUIRE_TIMEOUT = 5.0


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
