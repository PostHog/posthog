from datetime import date, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.models.user import User

from products.web_analytics.backend.weekly_digest import DEFAULT_DIGEST_EXECUTION_MODE, build_team_digest

# Below this many weekly visitors we don't try to assign a "real" persona — we
# celebrate the start of the journey instead of surfacing a thin, discouraging stat.
LOW_TRAFFIC_THRESHOLD = 25

# Round numbers we treat as celebratable visitor milestones when crossed week over week.
VISITOR_MILESTONES = [100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000]

_SEARCH_DOMAINS = ("google", "bing", "duckduckgo", "yahoo", "baidu", "yandex", "ecosia", "brave")
_SOCIAL_DOMAINS = (
    "twitter",
    "x.com",
    "t.co",
    "facebook",
    "linkedin",
    "reddit",
    "youtube",
    "instagram",
    "news.ycombinator",
    "producthunt",
    "tiktok",
    "mastodon",
    "bsky",
)

PERSONAS: dict[str, dict[str, str]] = {
    "just_getting_started": {
        "name": "The Newcomer",
        "emoji": "🐣",
        "blurb": "Every big site starts with a first visitor. The journey is underway.",
        "color": "#8f55e0",
    },
    "conversion_machine": {
        "name": "Conversion Machine",
        "emoji": "🎯",
        "blurb": "Conversions jumped {value} this week. Your funnel is firing.",
        "color": "#2f7d4f",
    },
    "traffic_magnet": {
        "name": "Traffic Magnet",
        "emoji": "🧲",
        "blurb": "Visitors surged {value} this week. Whatever you're doing, keep doing it.",
        "color": "#e0a23b",
    },
    "crowd_favorite": {
        "name": "Crowd Favorite",
        "emoji": "⭐",
        "blurb": "One page stole the show, pulling {value} of all your visitors.",
        "color": "#db5a9a",
    },
    "search_hog": {
        "name": "Search Sensation",
        "emoji": "🔍",
        "blurb": "Search engines sent the crowd this week, and {value} led the way.",
        "color": "#3b8fe0",
    },
    "word_of_mouth": {
        "name": "The Influencer",
        "emoji": "📣",
        "blurb": "People are spreading the word, and {value} drove your biggest referral.",
        "color": "#e0653b",
    },
    "loyal_following": {
        "name": "Cult Classic",
        "emoji": "💚",
        "blurb": "Your visitors stuck around. Engagement is up and bounce is down.",
        "color": "#2f9d7d",
    },
    "rising_star": {
        "name": "Rising Star",
        "emoji": "🚀",
        "blurb": "Across the board, this week beat last week. You're on the way up.",
        "color": "#6a5af0",
    },
    "steady_hog": {
        "name": "Old Faithful",
        "emoji": "🦔",
        "blurb": "A calm, consistent week. Steady traffic is its own kind of win.",
        "color": "#7a8089",
    },
}


def _signed_percent(metric: dict | None) -> int:
    """Return the week-over-week change as a signed integer percent (Up positive, Down negative)."""
    change = metric.get("change") if metric else None
    if not change:
        return 0
    percent = change.get("percent", 0)
    return percent if change.get("direction") == "Up" else -percent


def _domain_matches(name: str, needles: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(needle in lowered for needle in needles)


def compute_persona(digest: dict) -> dict:
    """Assign a single weekly persona from the digest data.

    Deterministic, priority-ordered, and pure so it can be unit-tested without ClickHouse.
    The first matching rule wins; the fallback is always a valid, warm identity.
    """
    visitors = digest.get("visitors") or {}
    visitors_current = visitors.get("current") or 0
    visitors_change = _signed_percent(visitors)
    pageviews_change = _signed_percent(digest.get("pageviews"))
    sessions_change = _signed_percent(digest.get("sessions"))
    bounce_change = _signed_percent(digest.get("bounce_rate"))
    duration_change = _signed_percent(digest.get("avg_session_duration"))

    top_pages = digest.get("top_pages") or []
    top_sources = digest.get("top_sources") or []
    goals = digest.get("goals") or []

    def persona(persona_id: str, value: str = "") -> dict:
        base = PERSONAS[persona_id]
        return {**base, "id": persona_id, "blurb": base["blurb"].replace("{value}", value)}

    if visitors_current < LOW_TRAFFIC_THRESHOLD:
        return persona("just_getting_started")

    top_goal_change = _signed_percent(goals[0]) if goals else 0
    if goals and top_goal_change >= 20:
        return persona("conversion_machine", f"+{top_goal_change}%")

    if visitors_change >= 30:
        return persona("traffic_magnet", f"+{visitors_change}%")

    if top_pages and visitors_current:
        top_page_share = min(round((top_pages[0].get("visitors") or 0) / visitors_current * 100), 100)
        if top_page_share >= 50:
            return persona("crowd_favorite", f"{top_page_share}%")

    if top_sources:
        top_source_name = top_sources[0].get("name") or ""
        top_source_display = top_source_name or "Direct"
        top_source_share = (
            min(round((top_sources[0].get("visitors") or 0) / visitors_current * 100), 100) if visitors_current else 0
        )
        if _domain_matches(top_source_name, _SEARCH_DOMAINS):
            return persona("search_hog", top_source_display)
        if _domain_matches(top_source_name, _SOCIAL_DOMAINS) or top_source_share >= 30:
            return persona("word_of_mouth", top_source_display)

    if bounce_change < 0 or duration_change > 0:
        return persona("loyal_following")

    if visitors_change > 0 and (pageviews_change > 0 or sessions_change > 0):
        return persona("rising_star")

    return persona("steady_hog")


def _build_highlights(digest: dict, compare: bool = True) -> list[dict]:
    """Pull a few screenshot-worthy superlatives from the digest data."""
    highlights: list[dict] = []

    visitors = digest.get("visitors") or {}
    current = visitors.get("current") or 0
    previous = visitors.get("previous")
    if previous is None and compare:
        previous = 0
    if previous is not None:
        crossed = [threshold for threshold in VISITOR_MILESTONES if previous < threshold <= current]
        if crossed:
            highlights.append(
                {
                    "id": "milestone",
                    "emoji": "🎉",
                    "title": "Milestone unlocked",
                    "value": f"{max(crossed):,} visitors",
                    "detail": "You crossed a new visitor milestone this week.",
                }
            )

    top_pages = digest.get("top_pages") or []
    risers = [page for page in top_pages if _signed_percent(page) > 0]
    if risers:
        rising = max(risers, key=_signed_percent)
        highlights.append(
            {
                "id": "rising_page",
                "emoji": "📈",
                "title": "Rising star page",
                "value": rising.get("path") or "/",
                "detail": f"Up {_signed_percent(rising)}% in visitors week over week.",
            }
        )

    top_sources = digest.get("top_sources") or []
    if top_sources:
        top_source = top_sources[0]
        highlights.append(
            {
                "id": "top_source",
                "emoji": "🌐",
                "title": "Top source",
                "value": top_source.get("name") or "Direct",
                "detail": f"{top_source.get('visitors') or 0:,} visitors came from here.",
            }
        )

    return highlights[:3]


def _build_period_dates(team: Team, days: int) -> dict[str, date]:
    period_end = timezone.now().astimezone(ZoneInfo(team.timezone)).date()
    period_start = period_end - timedelta(days=days)
    return {
        "period_start": period_start,
        "period_end": period_end,
    }


def recap_url_for_team(team: Team, *, utm_source: str, utm_medium: str | None = None) -> str:
    """The single canonical link to a team's weekly recap, with attribution params."""
    params: dict[str, str] = {"utm_source": utm_source}
    if utm_medium:
        params["utm_medium"] = utm_medium
    return f"{settings.SITE_URL}/project/{team.pk}/web/recap?{urlencode(params)}"


def build_team_recap(
    team: Team,
    days: int = 7,
    compare: bool = True,
    *,
    execution_mode: ExecutionMode = DEFAULT_DIGEST_EXECUTION_MODE,
    user: User | None = None,
) -> dict:
    """Build the full weekly recap payload: the digest data plus the derived persona and highlights."""
    digest = build_team_digest(team, days=days, compare=compare, execution_mode=execution_mode, user=user)
    return {
        **digest,
        "persona": compute_persona(digest),
        "highlights": _build_highlights(digest, compare=compare),
        "period_label": f"Last {days} days",
        **_build_period_dates(team, days),
        "project_name": team.name,
        "recap_url": recap_url_for_team(team, utm_source="web_analytics_recap"),
    }
