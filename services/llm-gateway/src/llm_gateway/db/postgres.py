import asyncpg


async def init_db_pool(database_url: str, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        server_settings={"application_name": "llm-gateway"},
    )


async def close_db_pool(pool: asyncpg.Pool) -> None:
    await pool.close()
