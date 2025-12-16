import hashlib
from datetime import UTC, datetime

import asyncpg

from llm_gateway.auth.models import AuthenticatedUser, has_required_scope


def hash_token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def validate_oauth_token(token: str, pool: asyncpg.Pool) -> AuthenticatedUser | None:
    if not token.startswith("pha_"):
        return None

    token_checksum = hash_token_sha256(token)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT oat.id, oat.user_id, oat.scope, oat.expires,
                   u.current_team_id, oat.application_id
            FROM posthog_oauthaccesstoken oat
            JOIN posthog_user u ON oat.user_id = u.id
            WHERE oat.token_checksum = $1 AND u.is_active = true
            """,
            token_checksum,
        )

        if not row:
            return None

        if row["expires"] and row["expires"] < datetime.now(UTC):
            return None

        if not row["application_id"]:
            return None

        scopes = row["scope"].split() if row["scope"] else []
        if not has_required_scope(scopes):
            return None

        return AuthenticatedUser(
            user_id=row["user_id"],
            team_id=row["current_team_id"],
            auth_method="oauth",
            scopes=scopes,
        )
