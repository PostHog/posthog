from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import asyncpg
from cachetools import TTLCache

from llm_gateway.db.postgres import acquire_connection


@dataclass(frozen=True, kw_only=True, slots=True)
class AccountTrust:
    created_at: datetime
    score: int

    def allows_requests(self, now: datetime) -> bool:
        age = now - self.created_at
        if age >= timedelta(days=30):
            return True
        minimum_score = 7 if age < timedelta(days=7) else 3
        return self.score >= minimum_score


def _highest_score(raw: object) -> int:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return 0
    if not isinstance(raw, dict):
        return 0
    return max((score for score in raw.values() if type(score) is int and score >= 0), default=0)


class AccountTrustResolver:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        # Cache inputs, not decisions, so an age boundary takes effect on the next request.
        self._cache: TTLCache[int, AccountTrust] = TTLCache(maxsize=10_000, ttl=60, timer=time.monotonic)

    async def resolve(self, team_id: int) -> AccountTrust | None:
        cached = self._cache.get(team_id)
        if cached is not None:
            return cached

        async with acquire_connection(self._pool) as conn:
            row = await conn.fetchrow(
                """
                SELECT o.created_at, o.customer_trust_scores
                FROM posthog_team t
                JOIN posthog_organization o ON o.id = t.organization_id
                WHERE t.id = $1
                """,
                team_id,
            )
        if row is None:
            return None

        trust = AccountTrust(created_at=row["created_at"], score=_highest_score(row["customer_trust_scores"]))
        self._cache[team_id] = trust
        return trust
