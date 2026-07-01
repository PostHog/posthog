import threading

from cachetools import TTLCache

from posthog.hogql.database.database import Database, HogQLDatabaseSources

from posthog.models import Team

# The fingerprint-embedding merge activity runs a HogQL query per fingerprint, and every HogQL
# execution otherwise rebuilds the team's HogQL database from scratch — firing a batch of Postgres
# queries (DataWarehouseSavedQuery, group types, feature flags, ...) each time. These embedding
# queries only ever read fixed ClickHouse system tables (document_embeddings_*), never warehouse
# tables, so the team's fetched sources can be reused across invocations. We cache the immutable
# sources bundle per team and rebuild a fresh, thread-owned Database from it, keeping the hot path
# off Postgres. A short TTL bounds staleness and memory across the worker's many teams.
SOURCES_CACHE_TTL_SECONDS = 300
SOURCES_CACHE_MAX_TEAMS = 2000

_sources_cache: TTLCache[int, HogQLDatabaseSources] = TTLCache(
    maxsize=SOURCES_CACHE_MAX_TEAMS, ttl=SOURCES_CACHE_TTL_SECONDS
)
_sources_cache_lock = threading.Lock()


def _cached_sources(team: Team) -> HogQLDatabaseSources:
    with _sources_cache_lock:
        sources = _sources_cache.get(team.id)
    if sources is not None:
        return sources

    # Fetched outside the lock: the fetch is exactly the Postgres load we want to avoid holding
    # every activity thread on. A cold-start race just fetches a couple of extra times before the
    # entry lands, which is harmless.
    sources = Database.fetch_sources(team=team)
    with _sources_cache_lock:
        _sources_cache[team.id] = sources
    return sources


def embedding_query_database(team: Team) -> Database:
    """A freshly built (thread-owned) HogQL Database for the team, rebuilt from a cached sources bundle
    so execute_hogql_query can skip the per-query Database._fetch_sources Postgres round-trips."""
    return Database.build_from_sources(_cached_sources(team))


def clear_sources_cache() -> None:
    with _sources_cache_lock:
        _sources_cache.clear()
