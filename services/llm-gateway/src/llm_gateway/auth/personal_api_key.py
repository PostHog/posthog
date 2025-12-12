import hashlib

import asyncpg

from llm_gateway.auth.models import AuthenticatedUser, has_required_scope


def hash_key_value_sha256(value: str) -> str:
    hashed = hashlib.sha256(value.encode()).hexdigest()
    return f"sha256${hashed}"


async def validate_personal_api_key(token: str, pool: asyncpg.Pool) -> AuthenticatedUser | None:
    if not token.startswith("phx_"):
        return None

    secure_value = hash_key_value_sha256(token)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT pak.id, pak.user_id, pak.scopes, u.current_team_id
            FROM posthog_personalapikey pak
            JOIN posthog_user u ON pak.user_id = u.id
            WHERE pak.secure_value = $1 AND u.is_active = true
            """,
            secure_value,
        )

        if not row:
            return None

        scopes = row["scopes"] or []
        if not has_required_scope(scopes):
            return None

        return AuthenticatedUser(
            user_id=row["user_id"],
            team_id=row["current_team_id"],
            auth_method="personal_api_key",
            scopes=scopes,
        )
