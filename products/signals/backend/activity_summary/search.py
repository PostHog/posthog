"""Search the activity summaries of a project's members, for scout reviewer routing.

A keyword search matches the query terms in the profile, the headline, the theme labels and the names of
owned and watched objects. A semantic search ranks each member by the best distance to the query among the
vectors of their newest build, the `summary_text` one and the `summary_profile` one when it exists. A hybrid
search merges both rankings with reciprocal rank fusion, because the `summary_text` vector holds only the
headline and the theme labels, and many members have no `summary_profile` vector, so an object name or a
detail in the profile can match on keywords only. A failed semantic read leaves a hybrid search with the
keyword ranking.

The filters (object, product, mode, recent activity, members) combine with AND and run before ranking.

Only members in `team.all_users_with_access()` can match, so a person who lost access drops out.
"""

import re
import datetime
from collections.abc import Iterable, Sequence
from typing import Any, cast

from django.db import models
from django.db.models import prefetch_related_objects
from django.utils import timezone

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.activity_summary.config import ActivitySummaryConfig
from products.signals.backend.activity_summary.prompt import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_RENDERING,
    EMBEDDING_RENDERING_PROFILE,
)
from products.signals.backend.activity_summary.read import (
    SKIPPED_REBUILD_STATUSES,
    ActivitySummaryTheme,
    ActivitySummaryView,
    readable_config,
    ready_view,
)
from products.signals.backend.hybrid_search import SearchMode, SemanticSearchUnavailable, reciprocal_rank_fusion
from products.signals.backend.models import UserActivitySummary
from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.backend.report_embeddings import EMBEDDING_PRODUCT
from products.signals.backend.signal_metadata import EMBEDDING_MODEL

logger = structlog.get_logger(__name__)

SEARCH_FLAG = "activity-summary-search"
DEFAULT_LIMIT = 10
MAX_LIMIT = 25
MAX_OFFSET = 500
MAX_ACTIVE_SINCE_DAYS = 365
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

# `document_id` is `<user_id>:<date>`, so a member has one row per rendering and day with an update. The
# newest row of each rendering is its current vector. A build writes both renderings with the same
# timestamp, so a rendering older than the member's newest one is from an earlier build and drops out:
# an old profile vector cannot outrank the current summary. The user filter runs before the limit, so
# other filters cannot starve the result.
NEAREST_MEMBERS_SQL = f"""
SELECT user_id, min(distance) AS distance
FROM (
    SELECT
        user_id,
        built_at,
        max(built_at) OVER (PARTITION BY user_id) AS newest_built_at,
        cosineDistance(embedding, %(embedding)s) AS distance
    FROM (
        SELECT
            splitByChar(':', document_id)[1] AS user_id,
            rendering,
            argMax(embedding, (timestamp, inserted_at)) AS embedding,
            max(timestamp) AS built_at
        FROM {EMBEDDINGS_TABLE}
        WHERE team_id = %(team_id)s
          AND product = %(product)s
          AND document_type = %(document_type)s
          AND rendering IN %(renderings)s
        GROUP BY user_id, rendering
        HAVING user_id IN %(user_ids)s
    )
    WHERE length(embedding) = %(dimensions)s
)
WHERE built_at = newest_built_at
GROUP BY user_id
ORDER BY distance ASC, user_id ASC
LIMIT %(limit)s
"""


class ObjectRelation(models.TextChoices):
    ANY = "any"
    OWNED = "owned"
    WATCHED = "watched"


class SummaryObjectRelation(models.TextChoices):
    """The list of the summary an object came from."""

    OWNED = "owned"
    WATCHED = "watched"


class MatchKind(models.TextChoices):
    SEMANTIC = "semantic"
    HEADLINE = "headline"
    THEMES = "themes"
    OWNED = "owned"
    WATCHED = "watched"
    PROFILE = "profile"


@frozen
class SearchMatch:
    kind: MatchKind
    # A short excerpt around the first keyword match. Null for a semantic match.
    snippet: str | None = None


@frozen
class ActivitySummaryObject:
    # `owned` for an object the member changed, `watched` for one they open on many days.
    relation: str
    type: str
    id: str
    name: str
    # Set on an owned object only.
    edit_days: int | None
    # Set on a watched object only.
    open_days: int | None
    last_at: str | None
    # Set on a watched object only: true when someone else created it.
    not_theirs: bool | None


@frozen
class ActivitySummaryProducts:
    works_in: tuple[str, ...]
    visits: tuple[str, ...]


@frozen
class ActivitySummarySearchHit:
    user_uuid: str
    first_name: str
    last_name: str
    github_login: str | None
    # The fused rank score. Null when the search had no query, so the order is newest first.
    score: float | None
    matched_on: tuple[SearchMatch, ...]
    # The owned and watched objects that matched the object filter, or whose name matched a query term.
    objects: tuple[ActivitySummaryObject, ...]
    headline: str | None
    themes: tuple[ActivitySummaryTheme, ...]
    modes: tuple[str, ...]
    products: ActivitySummaryProducts
    generated_at: datetime.datetime | None
    stale: bool
    profile: str | None = None


@frozen
class ActivitySummarySearchResult:
    results: tuple[ActivitySummarySearchHit, ...]
    # All the members that matched, before `offset` and `limit`.
    total: int
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
class ObjectFilter:
    # A file system type, such as "insight" or "dashboard". A suffix after "/" is ignored.
    type: str | None = None
    # The short id for an insight, a notebook or a replay playlist, else the primary key.
    id: str | None = None
    relation: ObjectRelation = ObjectRelation.ANY


@frozen
class _Candidate:
    user: User
    view: ActivitySummaryView
    computed: dict[str, Any]
    # The owned and watched objects that matched the object filter, empty without one.
    objects: tuple[ActivitySummaryObject, ...] = ()


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
    object_filter: ObjectFilter | None = None,
    product: str | None = None,
    mode: str | None = None,
    active_since_days: int | None = None,
    user_uuids: Sequence[str] = (),
    exclude_user_uuids: Sequence[str] = (),
    include_profile: bool = False,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> ActivitySummarySearchResult | None:
    """Rank the members of `team` whose activity summary matches `query` and every filter, best first.

    With no query, the members that pass the filters come newest summary first. Returns `None` when the
    team is not enrolled for reads or the search flag is off. Raises `SemanticSearchUnavailable` only for a
    semantic search, because a hybrid one keeps its keyword ranking.
    """
    config = searchable_config(team)
    if config is None:
        return None
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, min(offset, MAX_OFFSET))
    if object_filter is not None and object_filter.type is None and object_filter.id is None:
        object_filter = None
    active_since = (
        timezone.now().astimezone(datetime.UTC).date() - datetime.timedelta(days=active_since_days)
        if active_since_days is not None
        else None
    )
    members = {user.id: user for user in team.all_users_with_access().order_by("id")}
    # Two queries, not a join: the summary's user FK has no database constraint.
    rows = UserActivitySummary.objects.for_team(team.id).filter(user_id__in=members.keys())
    included = {str(value) for value in user_uuids}
    excluded = {str(value) for value in exclude_user_uuids}
    candidates: dict[int, _Candidate] = {}
    ready_count = 0
    for row in rows:
        view = ready_view(row, config)
        if view is None:
            continue
        ready_count += 1
        user = members[row.user_id]
        user_uuid = str(user.uuid)
        if user_uuid in excluded or (included and user_uuid not in included):
            continue
        computed = view.computed or {}
        objects: tuple[ActivitySummaryObject, ...] = ()
        if object_filter is not None:
            objects = _filtered_objects(computed, object_filter)
            if not objects:
                continue
        if product and not _uses_product(computed, product):
            continue
        if mode and not _works_in_mode(view, mode):
            continue
        if active_since is not None and not _active_since(view, computed, active_since):
            continue
        candidates[row.user_id] = _Candidate(user=user, view=view, computed=computed, objects=objects)
    not_ready_count = len(members) - ready_count

    terms = _terms(query)
    if not query or not query.strip():
        ordered = sorted(
            candidates.values(),
            key=lambda c: c.view.generated_at or datetime.datetime.min.replace(tzinfo=datetime.UTC),
            reverse=True,
        )
        selected = ordered[offset : offset + limit]
        _prefetch_github_identities(selected)
        hits = [_hit(c, score=None, matches=(), terms=terms, include_profile=include_profile) for c in selected]
        return ActivitySummarySearchResult(
            results=tuple(hits), total=len(ordered), semantic_used=False, not_ready_count=not_ready_count
        )

    keyword_ranking: list[int] = []
    keyword_matches: dict[int, tuple[SearchMatch, ...]] = {}
    if search_mode != SearchMode.SEMANTIC:
        keyword_ranking, keyword_matches = _keyword_ranking(candidates, terms)

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

    scores = reciprocal_rank_fusion([keyword_ranking, semantic_ranking])
    semantic_ids = set(semantic_ranking)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    page = ranked[offset : offset + limit]
    _prefetch_github_identities([candidates[user_id] for user_id, _ in page])
    hits = [
        _hit(
            candidates[user_id],
            score=round(score, 6),
            matches=(
                *((SearchMatch(kind=MatchKind.SEMANTIC),) if user_id in semantic_ids else ()),
                *keyword_matches.get(user_id, ()),
            ),
            terms=terms,
            include_profile=include_profile,
        )
        for user_id, score in page
    ]
    return ActivitySummarySearchResult(
        results=tuple(hits), total=len(ranked), semantic_used=semantic_used, not_ready_count=not_ready_count
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
        _with_team_github_integrations,
    )

    users = [candidate.user for candidate in candidates]
    prefetch_related_objects(users, *_github_identity_prefetches())
    _with_team_github_integrations(users)


def _object_kind(object_type: str) -> str:
    """The base type of an object, such as "hog_function" for "hog_function/destination".

    Owned objects carry the snake case activity log scope, and watched ones the file system type, which can
    have a suffix. Both use the short id for the scopes in `computed._SHORT_ID_SCOPES`, so ids already agree."""
    return object_type.split("/", 1)[0].strip().lower()


def _summary_objects(computed: dict[str, Any], relation: ObjectRelation) -> Iterable[ActivitySummaryObject]:
    for key in SummaryObjectRelation:
        if relation not in (ObjectRelation.ANY, key.value):
            continue
        items = computed.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            yield ActivitySummaryObject(
                relation=key.value,
                type=str(item.get("type") or ""),
                id=str(item.get("id") or ""),
                name=str(item.get("name") or ""),
                edit_days=_int_or_none(item.get("edit_days")) if key == SummaryObjectRelation.OWNED else None,
                open_days=_int_or_none(item.get("open_days")) if key == SummaryObjectRelation.WATCHED else None,
                last_at=str(item["last_at"]) if item.get("last_at") else None,
                not_theirs=bool(item.get("not_theirs")) if key == SummaryObjectRelation.WATCHED else None,
            )


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _filtered_objects(computed: dict[str, Any], object_filter: ObjectFilter) -> tuple[ActivitySummaryObject, ...]:
    kind = _object_kind(object_filter.type) if object_filter.type else None
    return tuple(
        item
        for item in _summary_objects(computed, object_filter.relation)
        if (kind is None or _object_kind(item.type) == kind)
        and (object_filter.id is None or item.id == object_filter.id)
    )


def _works_in_mode(view: ActivitySummaryView, mode: str) -> bool:
    return mode in view.modes or any(theme.mode == mode for theme in view.themes)


def _active_since(view: ActivitySummaryView, computed: dict[str, Any], since: datetime.date) -> bool:
    seen = [theme.last_seen for theme in view.themes]
    seen.extend(item.last_at for item in _summary_objects(computed, ObjectRelation.ANY))
    return any(day is not None and day >= since for day in map(_date_or_none, seen))


def _date_or_none(value: str | None) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


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
    patterns = _term_patterns(terms)
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
                "renderings": [EMBEDDING_RENDERING, EMBEDDING_RENDERING_PROFILE],
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


def _term_patterns(terms: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(rf"\b{re.escape(term)}", re.IGNORECASE) for term in terms]


def _hit_objects(candidate: _Candidate, terms: list[str]) -> tuple[ActivitySummaryObject, ...]:
    if candidate.objects:
        return candidate.objects
    patterns = _term_patterns(terms)
    if not patterns:
        return ()
    return tuple(
        item
        for item in _summary_objects(candidate.computed, ObjectRelation.ANY)
        if any(pattern.search(item.name) for pattern in patterns)
    )


def _products(computed: dict[str, Any]) -> ActivitySummaryProducts:
    products = computed.get("products")
    if not isinstance(products, dict):
        return ActivitySummaryProducts(works_in=(), visits=())
    return ActivitySummaryProducts(
        works_in=tuple(str(value) for value in products.get("works_in") or () if isinstance(value, str)),
        visits=tuple(str(value) for value in products.get("visits") or () if isinstance(value, str)),
    )


def _hit(
    candidate: _Candidate,
    *,
    score: float | None,
    matches: tuple[SearchMatch, ...],
    terms: list[str],
    include_profile: bool,
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
        objects=_hit_objects(candidate, terms),
        headline=view.headline,
        themes=view.themes,
        modes=view.modes,
        products=_products(candidate.computed),
        generated_at=view.generated_at,
        stale=view.stale,
        profile=view.profile if include_profile else None,
    )
