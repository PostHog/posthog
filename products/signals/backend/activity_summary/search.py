"""Search the activity summaries of a project's members, for scout reviewer routing.

A keyword search matches the query terms in the profile, the headline, the theme labels and the names of
owned and watched objects. A semantic search ranks the newest `summary_text` vector of each member by its
distance to the query. A hybrid search merges both rankings with reciprocal rank fusion, because the vector
holds only the headline and the theme labels, so an object name or a detail in the profile matches on
keywords only. A failed semantic read leaves a hybrid search with the keyword ranking.

Only members in `team.all_users_with_access()` can match, so a person who lost access drops out.
"""

import re
import datetime
from collections.abc import Iterable, Sequence
from typing import Any, cast

from django.db import models
from django.db.models import prefetch_related_objects

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.activity_summary.config import ActivitySummaryConfig
from products.signals.backend.activity_summary.prompt import EMBEDDING_DOCUMENT_TYPE, EMBEDDING_RENDERING
from products.signals.backend.activity_summary.read import (
    SKIPPED_REBUILD_STATUSES,
    ActivitySummaryTheme,
    ActivitySummaryView,
    readable_config,
    ready_view,
)
from products.signals.backend.models import UserActivitySummary
from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.backend.report_embeddings import EMBEDDING_PRODUCT
from products.signals.backend.signal_metadata import EMBEDDING_MODEL

logger = structlog.get_logger(__name__)

SEARCH_FLAG = "activity-summary-search"
DEFAULT_LIMIT = 10
MAX_LIMIT = 25
# The standard constant from the reciprocal rank fusion paper. It keeps one top rank from outweighing
# agreement between the two rankings.
RRF_K = 60
# The member roster attaches activity only to a narrowed result, so a full roster stays small.
MAX_MEMBERS_WITH_ACTIVITY = 10
# The roster carries a short activity block per member, so it keeps only the most active objects.
MAX_MEMBER_ACTIVITY_OBJECTS = 5
EMBEDDING_TIMEOUT_S = 10.0
# A stalled read must end inside the MCP request deadline, so that a hybrid search can still return its keyword ranking.
VECTOR_READ_MAX_EXECUTION_S = 10
MIN_TERM_CHARS = 2
SNIPPET_RADIUS = 60

# The text-embedding-3-small-1536 table, which is the model `tick.emit_summary_embedding` writes.
EMBEDDINGS_TABLE = "distributed_posthog_document_embeddings_text_embedding_3_small_1536"

# `document_id` is `<user_id>:<date>`, so a member has one row per day with an update. The newest one is
# the current summary. The user filter runs before the limit, so other filters cannot starve the result.
NEAREST_MEMBERS_SQL = f"""
SELECT user_id, cosineDistance(embedding, %(embedding)s) AS distance
FROM (
    SELECT
        splitByChar(':', document_id)[1] AS user_id,
        argMax(embedding, (timestamp, inserted_at)) AS embedding
    FROM {EMBEDDINGS_TABLE}
    WHERE team_id = %(team_id)s
      AND product = %(product)s
      AND document_type = %(document_type)s
      AND rendering = %(rendering)s
    GROUP BY user_id
    HAVING user_id IN %(user_ids)s
)
WHERE length(embedding) = %(dimensions)s
ORDER BY distance ASC
LIMIT %(limit)s
"""


class SearchMode(models.TextChoices):
    HYBRID = "hybrid"
    SEMANTIC = "semantic"
    KEYWORD = "keyword"


class MatchKind(models.TextChoices):
    SEMANTIC = "semantic"
    HEADLINE = "headline"
    THEMES = "themes"
    OWNED = "owned"
    WATCHED = "watched"
    PROFILE = "profile"


class SemanticSearchUnavailable(Exception):
    """The query embedding or the vector read failed, so a semantic-only search has no ranking."""


@frozen
class SearchMatch:
    kind: MatchKind
    # A short excerpt around the first keyword match. Null for a semantic match.
    snippet: str | None = None


@frozen
class ActivitySummarySearchHit:
    user_uuid: str
    first_name: str
    last_name: str
    github_login: str | None
    # The fused rank score. Null when the search had no query, so the order is newest first.
    score: float | None
    matched_on: tuple[SearchMatch, ...]
    headline: str | None
    themes: tuple[ActivitySummaryTheme, ...]
    modes: tuple[str, ...]
    generated_at: datetime.datetime | None
    stale: bool
    profile: str | None = None


@frozen
class ActivitySummarySearchResult:
    results: tuple[ActivitySummarySearchHit, ...]
    # False when a hybrid search fell back to keywords, or when the search did not ask for vectors.
    semantic_used: bool
    # Members with access and no ready summary, so the caller can see how much of the project it covered.
    not_ready_count: int


@frozen
class MemberActivityObject:
    type: str
    name: str


@frozen
class MemberActivity:
    headline: str | None
    themes: tuple[str, ...]
    owned: tuple[MemberActivityObject, ...]
    watched: tuple[MemberActivityObject, ...]
    generated_at: datetime.datetime | None
    stale: bool


@frozen
class _Candidate:
    user: User
    view: ActivitySummaryView
    computed: dict[str, Any]


def search_enabled(team: Team) -> bool:
    organization_id = str(team.organization_id)
    try:
        return (
            feature_enabled_or_false(
                SEARCH_FLAG,
                organization_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                send_feature_flag_events=False,
                only_evaluate_locally=True,
            )
            is True
        )
    except Exception:
        logger.exception("activity_summary_search_flag_check_failed", team_id=team.id)
        return False


def searchable_config(team: Team) -> ActivitySummaryConfig | None:
    """The read config when `team` can search summaries: the team is enrolled for reads and the search flag is on."""
    config = readable_config(team)
    if config is None or not search_enabled(team):
        return None
    return config


def search_summaries(
    team: Team,
    *,
    query: str | None = None,
    search_mode: SearchMode = SearchMode.HYBRID,
    product: str | None = None,
    exclude_user_uuids: Sequence[str] = (),
    include_profile: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> ActivitySummarySearchResult | None:
    """Rank the members of `team` whose activity summary matches `query`, best first.

    Returns `None` when the team is not enrolled for reads or the search flag is off. Raises
    `SemanticSearchUnavailable` only for a semantic search, because a hybrid one keeps its keyword ranking.
    """
    config = searchable_config(team)
    if config is None:
        return None
    limit = max(1, min(limit, MAX_LIMIT))
    members = {user.id: user for user in team.all_users_with_access().order_by("id")}
    # Two queries, not a join: the summary's user FK has no database constraint.
    rows = UserActivitySummary.objects.for_team(team.id).filter(user_id__in=members.keys())
    excluded = {str(value) for value in exclude_user_uuids}
    candidates: dict[int, _Candidate] = {}
    ready_count = 0
    for row in rows:
        view = ready_view(row, config)
        if view is None:
            continue
        ready_count += 1
        candidate = _Candidate(user=members[row.user_id], view=view, computed=view.computed or {})
        if str(candidate.user.uuid) in excluded or (product and not _uses_product(candidate.computed, product)):
            continue
        candidates[row.user_id] = candidate
    not_ready_count = len(members) - ready_count

    if not query or not query.strip():
        ordered = sorted(
            candidates.values(),
            key=lambda c: c.view.generated_at or datetime.datetime.min.replace(tzinfo=datetime.UTC),
            reverse=True,
        )
        selected = ordered[:limit]
        _prefetch_github_identities(selected)
        hits = [_hit(c, score=None, matches=(), include_profile=include_profile) for c in selected]
        return ActivitySummarySearchResult(results=tuple(hits), semantic_used=False, not_ready_count=not_ready_count)

    keyword_ranking: list[int] = []
    keyword_matches: dict[int, tuple[SearchMatch, ...]] = {}
    if search_mode != SearchMode.SEMANTIC:
        keyword_ranking, keyword_matches = _keyword_ranking(candidates, _terms(query))

    semantic_ranking: list[int] = []
    semantic_used = False
    if search_mode != SearchMode.KEYWORD and candidates:
        try:
            semantic_ranking = _semantic_ranking(team, query, candidates.keys(), limit=len(candidates))
            semantic_used = True
        except Exception as error:
            logger.exception("activity_summary_search_semantic_failed", team_id=team.id)
            if search_mode == SearchMode.SEMANTIC:
                raise SemanticSearchUnavailable() from error

    scores = _fuse([keyword_ranking, semantic_ranking])
    semantic_ids = set(semantic_ranking)
    top_scores = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
    _prefetch_github_identities([candidates[user_id] for user_id, _ in top_scores])
    hits = [
        _hit(
            candidates[user_id],
            score=round(score, 6),
            matches=(
                *((SearchMatch(kind=MatchKind.SEMANTIC),) if user_id in semantic_ids else ()),
                *keyword_matches.get(user_id, ()),
            ),
            include_profile=include_profile,
        )
        for user_id, score in top_scores
    ]
    return ActivitySummarySearchResult(
        results=tuple(hits), semantic_used=semantic_used, not_ready_count=not_ready_count
    )


def member_activities(team: Team, user_uuids: Sequence[str]) -> dict[str, MemberActivity] | None:
    """The ready activity summaries of the given members, keyed by user UUID.

    Returns `None` when the team is not enrolled for reads or the search flag is off. A member without
    a ready summary, or without access to `team`, has no key.
    """
    config = searchable_config(team)
    if config is None:
        return None
    members = {
        user_id: str(user_uuid)
        for user_id, user_uuid in team.all_users_with_access().filter(uuid__in=user_uuids).values_list("id", "uuid")
    }
    # Two queries, not a join: the summary's user FK has no database constraint.
    rows = UserActivitySummary.objects.for_team(team.id).filter(user_id__in=members.keys())
    activities: dict[str, MemberActivity] = {}
    for row in rows:
        view = ready_view(row, config)
        # Same readiness rule as `get_summary`: a stale summary whose rebuild skipped is not ready.
        if view is None or (view.stale and row.status in SKIPPED_REBUILD_STATUSES):
            continue
        computed = view.computed or {}
        activities[members[row.user_id]] = MemberActivity(
            headline=view.headline,
            themes=tuple(theme.label for theme in view.themes),
            owned=_activity_objects(computed, "owned"),
            watched=_activity_objects(computed, "watched"),
            generated_at=view.generated_at,
            stale=view.stale,
        )
    return activities


def _activity_objects(computed: dict[str, Any], key: str) -> tuple[MemberActivityObject, ...]:
    items = computed.get(key)
    if not isinstance(items, list):
        return ()
    return tuple(
        MemberActivityObject(type=str(item.get("type") or ""), name=str(item.get("name") or ""))
        for item in items
        if isinstance(item, dict)
    )[:MAX_MEMBER_ACTIVITY_OBJECTS]


def _prefetch_github_identities(candidates: Sequence[_Candidate]) -> None:
    # Deferred: resolve_reviewers imports the engineering_analytics facade, which imports the signals facade.
    from products.signals.backend.report_generation.resolve_reviewers import (  # noqa: PLC0415
        _github_identity_prefetches,
    )

    prefetch_related_objects([candidate.user for candidate in candidates], *_github_identity_prefetches())


def _uses_product(computed: dict[str, Any], product: str) -> bool:
    products = computed.get("products")
    if not isinstance(products, dict):
        return False
    return any(isinstance(values, list) and product in values for values in products.values())


def _terms(query: str | None) -> list[str]:
    words = re.findall(r"\w+", (query or "").lower())
    return list(dict.fromkeys(word for word in words if len(word) >= MIN_TERM_CHARS))


def _object_names(computed: dict[str, Any], key: str) -> str:
    items = computed.get(key)
    if not isinstance(items, list):
        return ""
    return "\n".join(str(item.get("name") or "") for item in items if isinstance(item, dict))


def _keyword_fields(candidate: _Candidate) -> dict[MatchKind, str]:
    view = candidate.view
    return {
        MatchKind.HEADLINE: view.headline or "",
        MatchKind.THEMES: "\n".join(theme.label for theme in view.themes),
        MatchKind.OWNED: _object_names(candidate.computed, "owned"),
        MatchKind.WATCHED: _object_names(candidate.computed, "watched"),
        MatchKind.PROFILE: view.profile or "",
    }


def _snippet(text: str, start: int) -> str:
    lo, hi = max(0, start - SNIPPET_RADIUS), min(len(text), start + SNIPPET_RADIUS)
    return ("…" if lo else "") + " ".join(text[lo:hi].split()) + ("…" if hi < len(text) else "")


def _keyword_ranking(
    candidates: dict[int, _Candidate], terms: list[str]
) -> tuple[list[int], dict[int, tuple[SearchMatch, ...]]]:
    """Members that match at least one term, the most distinct terms first, then the most matched fields."""
    if not terms:
        return [], {}
    patterns = [re.compile(rf"\b{re.escape(term)}", re.IGNORECASE) for term in terms]
    ranked: list[tuple[int, int, int]] = []
    matches: dict[int, tuple[SearchMatch, ...]] = {}
    for user_id, candidate in candidates.items():
        matched_terms: set[int] = set()
        found: list[SearchMatch] = []
        for kind, text in _keyword_fields(candidate).items():
            first: int | None = None
            for index, pattern in enumerate(patterns):
                if (match := pattern.search(text)) is not None:
                    matched_terms.add(index)
                    first = match.start() if first is None else min(first, match.start())
            if first is not None:
                found.append(SearchMatch(kind=kind, snippet=_snippet(text, first)))
        if found:
            ranked.append((user_id, len(matched_terms), len(found)))
            matches[user_id] = tuple(found)
    ranked.sort(key=lambda item: (-item[1], -item[2], item[0]))
    return [user_id for user_id, _, _ in ranked], matches


def _semantic_ranking(team: Team, query: str, user_ids: Iterable[int], *, limit: int) -> list[int]:
    # Deferred: `posthog.api` loads the product routes, which import this module through the signals facade.
    from posthog.api.embedding_worker import generate_embedding  # noqa: PLC0415

    embedding = generate_embedding(team, query, model=EMBEDDING_MODEL.value, timeout=EMBEDDING_TIMEOUT_S).embedding
    tag_queries(
        product=Product.SIGNALS, feature=Feature.ENRICHMENT, team_id=team.id, query_type="activity_summary_search"
    )
    rows = cast(
        list[tuple[Any, ...]],
        sync_execute(
            NEAREST_MEMBERS_SQL,
            {
                "embedding": embedding,
                "team_id": team.id,
                "product": EMBEDDING_PRODUCT,
                "document_type": EMBEDDING_DOCUMENT_TYPE,
                "rendering": EMBEDDING_RENDERING,
                "user_ids": [str(user_id) for user_id in user_ids],
                "dimensions": EMBEDDING_DIMENSIONS,
                "limit": limit,
            },
            settings={"max_execution_time": VECTOR_READ_MAX_EXECUTION_S, "timeout_overflow_mode": "throw"},
            # A scout run calls this, and no person waits on the result.
            workload=Workload.OFFLINE,
            team_id=team.id,
            ch_user=ClickHouseUser.SIGNALS,
        )
        or [],
    )
    return [int(user_id) for user_id, _ in rows]


def _fuse(rankings: Sequence[Sequence[int]]) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, user_id in enumerate(ranking, start=1):
            scores[user_id] = scores.get(user_id, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def _hit(
    candidate: _Candidate, *, score: float | None, matches: tuple[SearchMatch, ...], include_profile: bool
) -> ActivitySummarySearchHit:
    user, view = candidate.user, candidate.view
    login = user.get_github_login()
    return ActivitySummarySearchHit(
        user_uuid=str(user.uuid),
        first_name=user.first_name,
        last_name=user.last_name,
        github_login=login.lower() if login else None,
        score=score,
        matched_on=matches,
        headline=view.headline,
        themes=view.themes,
        modes=view.modes,
        generated_at=view.generated_at,
        stale=view.stale,
        profile=view.profile if include_profile else None,
    )
