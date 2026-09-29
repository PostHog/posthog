import math
import datetime as dt
from typing import Any
from urllib.parse import urlparse

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.aeo.backend.facade.api import list_citation_gaps
from products.aeo.backend.facade.contracts import CitationGap
from products.web_analytics.backend.content_autopilot.lifecycle import (
    ContentAutopilotLifecycleError,
    canonical_team_id,
    lock_profile,
    start_run,
)
from products.web_analytics.backend.content_autopilot.site_discovery import read_sitemap_urls, site_host
from products.web_analytics.backend.models import (
    ContentAutopilotOpportunity,
    ContentAutopilotProposal,
    ContentAutopilotRun,
    ContentAutopilotSiteProfile,
)

OPPORTUNITY_LOOKBACK_DAYS = 14
MAX_DRAFTS_PER_RUN = 5
SITEMAP_CACHE_SECONDS = 6 * 60 * 60
FULL_CONFIDENCE_CHECKS = 9
FULL_TRAFFIC_SIGNAL = 100
SITE_PAGE_VIEWS_LOOKBACK_DAYS = 30
MAX_ANSWER_CHARS_IN_GAP = 4000

ENGINE_LABELS = {
    "claude-web-search": "Claude",
    "openai-web-search": "ChatGPT",
    "exa-answer": "Exa",
}


def engine_label(engine: str) -> str:
    return ENGINE_LABELS.get(engine, engine)


def canonical_site_url(url: str, *, origin: str, page_urls: list[str]) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    path = parsed.path.rstrip("/") or "/"
    host = site_host(url)
    if not host or host != site_host(origin) or path == "/":
        return None
    if not page_urls:
        return f"{origin.rstrip('/')}{path}"
    return next((page for page in page_urls if (urlparse(page).path.rstrip("/") or "/") == path), None)


def score_gap(gap: CitationGap, traffic: dict[str, int] | None = None) -> float:
    severity = 1 - gap.citation_rate
    agreement = len(gap.engines_not_citing) / len(gap.engines) if gap.engines else 0.0
    mentioned_not_cited = max(0, gap.mentioned_checks - gap.cited_checks) / gap.checks if gap.checks else 0.0
    ai_traffic = (traffic or {}).get("ai_visitors", 0) + (traffic or {}).get("ai_crawls", 0) / 10
    traffic_signal = min(1.0, math.log1p(ai_traffic) / math.log1p(FULL_TRAFFIC_SIGNAL))
    confidence = min(1.0, gap.checks / FULL_CONFIDENCE_CHECKS)
    priority = 0.45 * severity + 0.25 * agreement + 0.2 * mentioned_not_cited + 0.1 * traffic_signal
    return round(priority * (0.5 + 0.5 * confidence), 4)


def site_page_urls(profile: ContentAutopilotSiteProfile) -> list[str]:
    cache_key = f"content_autopilot:sitemap:{profile.id}:{profile.updated_at.timestamp()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    urls = read_sitemap_urls(list(profile.source_urls), origin=profile.domain)
    boundaries = [str(boundary) for boundary in profile.content_boundaries] or ["/"]
    urls = [url for url in urls if any(urlparse(url).path.startswith(boundary) for boundary in boundaries)]
    cache.set(cache_key, urls, SITEMAP_CACHE_SECONDS)
    return urls


def page_ai_traffic(team: Team, paths: list[str]) -> dict[str, dict[str, int]]:
    if not paths:
        return {}
    query = parse_select(
        """
        SELECT
            coalesce(nullIf(trimRight(properties.$pathname, '/'), ''), '/') AS path,
            countIf(`$virt_is_bot` = true AND `$virt_traffic_category` IN ('ai_crawler', 'ai_assistant', 'ai_search')) AS ai_crawls,
            uniqIf(person_id, event = '$pageview' AND NOT `$virt_is_bot` AND session.$channel_type = 'AI') AS ai_visitors
        FROM events
        WHERE timestamp >= now() - toIntervalDay({lookback_days})
            AND event IN ('$pageview', '$http_log')
            AND properties.$pathname IN {paths}
        GROUP BY path
        """,
        placeholders={
            "lookback_days": ast.Constant(value=OPPORTUNITY_LOOKBACK_DAYS),
            "paths": ast.Tuple(
                exprs=[ast.Constant(value=variant) for path in paths for variant in {path, f"{path.rstrip('/')}/"}]
            ),
        },
    )
    with tags_context(
        product=Product.WEB_ANALYTICS, feature=Feature.ENRICHMENT, team_id=team.pk, org_id=team.organization_id
    ):
        response = execute_hogql_query(query=query, team=team, query_type="content_autopilot_page_ai_traffic")
    return {
        str(row[0]): {"ai_crawls": int(row[1] or 0), "ai_visitors": int(row[2] or 0)} for row in response.results or []
    }


def _page_path(url: str) -> str:
    return urlparse(url).path.rstrip("/") or "/"


def _most_viewed_paths(team: Team, origin: str, limit: int) -> list[str]:
    query = parse_select(
        """
        SELECT properties.$pathname AS path, count() AS views
        FROM events
        WHERE event = '$pageview'
            AND timestamp >= now() - toIntervalDay({lookback_days})
            AND lower(properties.$host) IN {hosts}
        GROUP BY path
        ORDER BY views DESC
        LIMIT {limit}
        """,
        placeholders={
            "lookback_days": ast.Constant(value=SITE_PAGE_VIEWS_LOOKBACK_DAYS),
            "hosts": ast.Tuple(
                exprs=[ast.Constant(value=host) for host in (site_host(origin), f"www.{site_host(origin)}")]
            ),
            "limit": ast.Constant(value=limit),
        },
    )
    with tags_context(
        product=Product.WEB_ANALYTICS, feature=Feature.ENRICHMENT, team_id=team.pk, org_id=team.organization_id
    ):
        response = execute_hogql_query(query=query, team=team, query_type="content_autopilot_most_viewed_pages")
    return [_page_path(str(row[0])) for row in response.results or [] if row[0]]


def top_site_pages(team: Team, *, origin: str, page_urls: list[str], limit: int) -> list[str]:
    by_path: dict[str, str] = {}
    for url in page_urls:
        by_path.setdefault(_page_path(url), url)
    try:
        viewed = [by_path[path] for path in _most_viewed_paths(team, origin, limit * 2) if path in by_path]
    except Exception as error:
        capture_exception(error)
        viewed = []
    shallow = [url for url in page_urls if len([part for part in urlparse(url).path.split("/") if part]) <= 1]
    return list(dict.fromkeys([*viewed, *shallow, *page_urls]))[:limit]


def _join_labels(labels: list[str]) -> str:
    if len(labels) <= 1:
        return "".join(labels)
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def _evidence(gap: CitationGap, target_url: str, traffic: dict[str, int] | None) -> list[dict[str, str]]:
    missing = [engine_label(engine) for engine in gap.engines_not_citing]
    uncited = gap.checks - gap.cited_checks
    explanation = (
        f"{_join_labels(missing)} answered without citing the site in {uncited} of {gap.checks} "
        f"{'check' if gap.checks == 1 else 'checks'} over the last {OPPORTUNITY_LOOKBACK_DAYS} days."
    )
    if gap.competitor_domains:
        explanation += f" They cited {_join_labels(list(gap.competitor_domains[:3]))} instead."
    evidence = [{"opportunity_kind": "ai_visibility_gap", "explanation": explanation, "query": gap.prompt_text}]
    if target_url:
        page_explanation = "AI assistants cited this page in some of their answers to this question."
        if traffic is not None:
            page_explanation += (
                f" In the last {OPPORTUNITY_LOOKBACK_DAYS} days AI crawlers fetched it {traffic['ai_crawls']} times "
                f"and {traffic['ai_visitors']} visitors arrived from AI assistants."
            )
        evidence.append(
            {"opportunity_kind": "ai_visibility_gap", "explanation": page_explanation, "page_url": target_url}
        )
    return evidence


def _gap_payload(gap: CitationGap) -> dict[str, Any]:
    return {
        "checks": gap.checks,
        "cited_checks": gap.cited_checks,
        "mentioned_checks": gap.mentioned_checks,
        "citation_rate": gap.citation_rate,
        "engines": list(gap.engines),
        "engines_not_citing": list(gap.engines_not_citing),
        "competitor_urls": list(gap.competitor_urls),
        "competitor_domains": list(gap.competitor_domains),
        "engine_search_queries": list(gap.engine_search_queries),
        "our_cited_urls": list(gap.our_cited_urls),
        "latest_answers": [
            {
                "engine": answer.engine,
                "answer_text": answer.answer_text[:MAX_ANSWER_CHARS_IN_GAP],
                "checked_at": answer.checked_at.isoformat(),
            }
            for answer in gap.latest_answers
        ],
        "last_checked_at": gap.last_checked_at.isoformat(),
    }


def refresh_opportunities(
    *, team: Team, profile_id: str, page_urls: list[str] | None = None
) -> list[ContentAutopilotOpportunity]:
    team_id = canonical_team_id(team)
    try:
        profile = ContentAutopilotSiteProfile.objects.for_team(team_id, canonical=True).get(
            id=profile_id, deleted=False
        )
    except ContentAutopilotSiteProfile.DoesNotExist as error:
        raise ContentAutopilotLifecycleError("That site could not be found.") from error
    gaps = list_citation_gaps(team_id, since=timezone.now() - dt.timedelta(days=OPPORTUNITY_LOOKBACK_DAYS))
    if page_urls is None:
        page_urls = site_page_urls(profile) if gaps else []

    targets: dict[str, str] = {}
    for gap in gaps:
        cited = (canonical_site_url(url, origin=profile.domain, page_urls=page_urls) for url in gap.our_cited_urls)
        targets[gap.prompt_hash] = next((url for url in cited if url), "")

    paths = sorted({_page_path(url) for url in targets.values() if url})
    traffic_by_path = page_ai_traffic(team, paths)

    now = timezone.now()
    with transaction.atomic():
        existing = {
            opportunity.cluster_key: opportunity
            for opportunity in ContentAutopilotOpportunity.objects.for_team(team_id, canonical=True)
            .select_for_update()
            .filter(profile=profile)
        }
        for gap in gaps:
            target_url = targets[gap.prompt_hash]
            traffic = traffic_by_path.get(_page_path(target_url))
            fields = {
                "aeo_prompt_id": gap.prompt_id,
                "title": gap.prompt_text,
                "score": score_gap(gap, traffic),
                "recommended_type": (
                    ContentAutopilotProposal.ProposalType.PAGE_IMPROVEMENT
                    if target_url
                    else ContentAutopilotProposal.ProposalType.NEW_CONTENT
                ),
                "target_url": target_url,
                "evidence": _evidence(gap, target_url, traffic),
                "gap": _gap_payload(gap),
                "last_refreshed_at": now,
            }
            opportunity = existing.get(gap.prompt_hash)
            if opportunity is None:
                ContentAutopilotOpportunity.objects.for_team(team_id, canonical=True).create(
                    team_id=team_id, profile=profile, cluster_key=gap.prompt_hash, **fields
                )
                continue
            if opportunity.status == ContentAutopilotOpportunity.Status.QUEUED:
                continue
            for name, value in fields.items():
                setattr(opportunity, name, value)
            opportunity.save(update_fields=[*fields.keys(), "updated_at"])

    return list_opportunities(team=team, profile_id=profile_id)


def list_opportunities(*, team: Team, profile_id: str) -> list[ContentAutopilotOpportunity]:
    return list(
        ContentAutopilotOpportunity.objects.for_team(canonical_team_id(team), canonical=True)
        .filter(profile_id=profile_id, profile__deleted=False)
        .order_by("-score", "title")
    )


def _lock_opportunities(team_id: int, opportunity_ids: list[str]) -> list[ContentAutopilotOpportunity]:
    opportunities = list(
        ContentAutopilotOpportunity.objects.for_team(team_id, canonical=True)
        .select_for_update()
        .filter(id__in=opportunity_ids, profile__deleted=False)
    )
    if len(opportunities) != len(set(opportunity_ids)):
        raise ContentAutopilotLifecycleError("One or more opportunities could not be found.")
    return opportunities


def dismiss_opportunity(*, team: Team, opportunity_id: str) -> ContentAutopilotOpportunity:
    with transaction.atomic():
        (opportunity,) = _lock_opportunities(canonical_team_id(team), [opportunity_id])
        if opportunity.status == ContentAutopilotOpportunity.Status.QUEUED:
            raise ContentAutopilotLifecycleError("This opportunity is being drafted and can't be dismissed.")
        opportunity.status = ContentAutopilotOpportunity.Status.DISMISSED
        opportunity.save(update_fields=["status", "updated_at"])
        return opportunity


def draft_opportunities(
    *, team: Team, profile_id: str, opportunity_ids: list[str], triggered_by_id: int | None
) -> ContentAutopilotRun:
    if not opportunity_ids:
        raise ContentAutopilotLifecycleError("Select at least one opportunity to draft.")
    if len(set(opportunity_ids)) > MAX_DRAFTS_PER_RUN:
        raise ContentAutopilotLifecycleError(f"Draft up to {MAX_DRAFTS_PER_RUN} opportunities at a time.")
    team_id = canonical_team_id(team)
    with transaction.atomic():
        lock_profile(team_id, profile_id)
        opportunities = _lock_opportunities(team_id, opportunity_ids)
        if any(str(opportunity.profile_id) != str(profile_id) for opportunity in opportunities):
            raise ContentAutopilotLifecycleError("Every opportunity must belong to the selected site.")
        if any(opportunity.status == ContentAutopilotOpportunity.Status.QUEUED for opportunity in opportunities):
            raise ContentAutopilotLifecycleError("One or more opportunities are already being drafted.")
        run = start_run(team=team, profile_id=profile_id, triggered_by_id=triggered_by_id)
        for opportunity in opportunities:
            opportunity.status = ContentAutopilotOpportunity.Status.QUEUED
            opportunity.run = run
            opportunity.save(update_fields=["status", "run", "updated_at"])
        return run
