from __future__ import annotations

import re
import hmac
import json
import hashlib
from collections.abc import Callable
from dataclasses import field
from datetime import timedelta
from time import monotonic

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.query_creator_access import creator_access_revoked
from posthog.redis import get_client

from products.signals.backend.models import SignalReport, SignalScoutRun
from products.signals.backend.slack_formatting import escape_slack_mrkdwn

logger = structlog.get_logger(__name__)

# Each render can hold the Celery worker for the facade's RENDER_TIMEOUT, and the delivery task
# retries the whole message on transient failure, so both the count and the total time are bounded.
# A render only starts if it can finish inside the budget, so the budget is the worst case, not the
# point after which no more start. Charts past either bound still show in the inbox; the Slack
# message just links there.
MAX_SLACK_REPORT_CHARTS = 3
SLACK_REPORT_CHART_RENDER_BUDGET_SECONDS = 240

# Slack re-fetches image_url after the message is posted, so the token has to outlive the post
# by a comfortable margin; matches what task-run chart delivery uses.
SLACK_REPORT_CHART_URL_TTL = timedelta(days=30)

# The delivery task retries the whole message when Slack fails, and its backoff can span hours.
# Rendered asset ids are remembered per delivery for longer than that, so a retry re-posts the
# same PNGs instead of launching every export workflow again. Entries are keyed by chart id plus a
# fingerprint of the query, since an edit may swap a chart's query under the same id.
_RENDERED_ASSETS_CACHE_TTL_SECONDS = 24 * 60 * 60

# The exporter renders an InsightVizNode-wrapped query; a SavedInsightNode is rendered through the
# insight it points at. DataVisualizationNode (SQL) has no PNG render path yet, so it is left to
# the inbox.
_RENDERABLE_CHART_KINDS = frozenset({"InsightVizNode", "SavedInsightNode"})

# Every block a chart contributes carries a block id under this prefix, so a delivery Slack rejects
# can drop the charts as whole units — title, image, and caption — and post the prose it can accept.
CHART_BLOCK_ID_PREFIX = "signals-scout-chart:"

# The chart ids the summary points at, in the order the prose reaches them. Deliberately looser
# than the inbox's link parse: this only decides which charts go first when the cap bites, and
# a false positive costs nothing more than ordering.
_CHART_REF_ID_RE = re.compile(r"chart:([a-z0-9][a-z0-9_-]*)")


def _referenced_chart_ids(summary: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in _CHART_REF_ID_RE.finditer(summary):
        seen.setdefault(match.group(1), None)
    return list(seen)


def _ordered_charts(report: SignalReport) -> list[dict]:
    charts = [chart for chart in (report.charts or []) if isinstance(chart, dict)]
    by_id = {chart.get("chart_id"): chart for chart in charts if isinstance(chart.get("chart_id"), str)}
    referenced = [by_id[chart_id] for chart_id in _referenced_chart_ids(report.summary or "") if chart_id in by_id]
    referenced_ids = {chart["chart_id"] for chart in referenced}
    unreferenced = [chart for chart in charts if chart.get("chart_id") not in referenced_ids]
    return referenced + unreferenced


def _render_chart_asset_id(*, team: Team, created_by: User, query: dict) -> int | None:
    # The exports facade drags temporalio and the query schema in with it, and the signals app's
    # startup wiring reaches this module, so the facade stays off the django.setup() path.
    from products.exports.backend.facade.api import render_png_export  # noqa: PLC0415

    # A system render stays out of the acting user's export quota and the stuck-export sweep, and it
    # expires with the delivery url, its only reference; the format default would keep the PNG for
    # months after the url stopped working.
    render_kwargs: dict = {
        "team": team,
        "created_by": created_by,
        "is_system": True,
        "expires_after": timezone.now() + SLACK_REPORT_CHART_URL_TTL,
    }
    kind = query.get("kind")
    if kind == "SavedInsightNode":
        short_id = query.get("shortId")
        if not isinstance(short_id, str) or not short_id:
            return None
        asset, png = render_png_export(insight_short_id=short_id, **render_kwargs)
    else:
        asset, png = render_png_export(export_context={"source": query}, **render_kwargs)
    if png is None:
        logger.warning("signals_scout.slack_report_chart_render_failed", asset_id=asset.id, error=asset.exception)
        return None
    return asset.id


def _chart_blocks(chart: dict, image_url: str, position: int) -> list[dict]:
    title = " ".join(str(chart.get("title") or "Chart").split())
    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{escape_slack_mrkdwn(title)}*"}},
        {"type": "image", "image_url": image_url, "alt_text": title[:2000]},
    ]
    caption = chart.get("caption")
    if isinstance(caption, str) and caption.strip():
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": escape_slack_mrkdwn(caption.strip())}]}
        )
    for index, block in enumerate(blocks):
        block["block_id"] = f"{CHART_BLOCK_ID_PREFIX}{position}:{index}"
    return blocks


def _is_chart_block(block: dict) -> bool:
    return str(block.get("block_id") or "").startswith(CHART_BLOCK_ID_PREFIX)


def strip_chart_blocks(blocks: list[dict]) -> list[dict]:
    """Drop every chart block, leaving the prose and the report link.

    Slack fetches each `image_url` itself and rejects the whole message when it cannot reach one, so
    a delivery Slack refuses can post this instead of losing the report."""
    return [block for block in blocks if not _is_chart_block(block)]


def has_chart_blocks(blocks: list[dict]) -> bool:
    return any(_is_chart_block(block) for block in blocks)


def _acting_user(run: SignalScoutRun, team: Team) -> User | None:
    """The user the scout ran as; the render is attributed to and access-checked against them.

    Delivery runs in a worker with no request to authenticate that user, so a creator who has since
    been deactivated, left the org, or lost access to a private project yields no principal. The
    membership test is the same one the runner uses to pick the acting user in the first place."""
    task_run = getattr(run, "task_run", None)
    task = getattr(task_run, "task", None)
    user = getattr(task, "created_by", None)
    if user is None or creator_access_revoked(user, team):
        return None
    if not team.all_users_with_access().filter(id=user.id).exists():
        return None
    return user


def _rendered_assets_cache_key(delivery_id: str) -> str:
    return f"signals_scout:slack_report_chart_assets:{delivery_id}"


def _rendered_asset_entry_key(chart_id: str, query: dict) -> str:
    fingerprint = hashlib.sha256(json.dumps(query, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return f"{chart_id}:{fingerprint}"


def _cache_signing_keys() -> list[str]:
    """Keys for the retry cache's entry signatures, newest first; empty means the cache is off.

    Its own rotatable setting rather than `SECRET_KEY`, so this domain can be rotated without
    disturbing Django's session and CSRF signing. Unprovisioned fails closed: no reuse."""
    return [key for key in settings.SIGNALS_SLACK_CHART_CACHE_SIGNING_KEYS if key]


def _sign_cached_asset(signing_key: str, cache_key: str, entry_key: str, asset_id: int) -> str:
    # HMAC over the delivery-scoped cache key, the chart entry key, and the asset id, so the cached
    # mapping is tamper-evident: a process with write access to the shared Redis can't forge or swap
    # an entry (even for another of the acting user's own assets) without a signing key.
    message = f"{cache_key}\x00{entry_key}\x00{asset_id}".encode()
    return hmac.new(signing_key.encode(), message, hashlib.sha256).hexdigest()[:32]


# Stored as JSON through the raw Redis client rather than Django's cache: the default cache backend
# pickles values, and a `cache.get` unpickles whatever bytes sit at the key, so a process that can
# write this shared Redis could plant a pickle payload that executes on read. A JSON round-trip has
# no such deserialization path, and each entry carries an HMAC so a substituted asset id is rejected
# on read. The cache only saves re-renders on retry; if it is down the message must still go out, so
# both sides degrade to "no reuse" rather than raising into the delivery task.
def _load_rendered_assets(cache_key: str | None) -> dict[str, int]:
    signing_keys = _cache_signing_keys()
    if cache_key is None or not signing_keys:
        return {}
    try:
        raw = get_client().get(cache_key)
    except Exception:
        logger.warning("signals_scout.slack_report_chart_cache_read_failed", exc_info=True)
        return {}
    if raw is None:
        return {}
    try:
        cached = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(cached, dict):
        return {}
    verified: dict[str, int] = {}
    for key, value in cached.items():
        # Each entry is [asset_id, signature]; keep only those whose signature we can reproduce, so a
        # tampered or forged entry (a swapped asset id, an unsigned int) is treated as a cache miss.
        if not (isinstance(value, list) and len(value) == 2):
            continue
        asset_id, signature = value
        if not (isinstance(asset_id, int) and not isinstance(asset_id, bool) and isinstance(signature, str)):
            continue
        # Every key verifies, so an entry signed before a rotation is still reusable.
        if any(
            hmac.compare_digest(signature, _sign_cached_asset(signing_key, cache_key, str(key), asset_id))
            for signing_key in signing_keys
        ):
            verified[str(key)] = asset_id
    return verified


def _store_rendered_assets(cache_key: str | None, rendered_assets: dict[str, int]) -> None:
    signing_keys = _cache_signing_keys()
    if cache_key is None or not signing_keys or not rendered_assets:
        return
    signed = {
        key: [asset_id, _sign_cached_asset(signing_keys[0], cache_key, key, asset_id)]
        for key, asset_id in rendered_assets.items()
    }
    try:
        get_client().set(cache_key, json.dumps(signed), ex=_RENDERED_ASSETS_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("signals_scout.slack_report_chart_cache_write_failed", exc_info=True)


@frozen(frozen=False)
class ChartRenderBudget:
    """What one Slack delivery may spend on chart renders, and what it has rendered so far.

    Mutable and shared across a delivery's initial build and any rebuild, so a report edited
    mid-render cannot hand the rebuild a fresh clock and a fresh set of export workflows. Only a
    cache miss spends a render; reusing an asset the delivery already rendered costs nothing here,
    so a rebuild whose charts are unchanged still shows them all. The rendered assets live here
    rather than only in the retry cache, so a rebuild keeps them even where that cache is off."""

    started: float
    renders_remaining: int = MAX_SLACK_REPORT_CHARTS
    rendered_assets: dict[str, int] = field(default_factory=dict)


def new_chart_render_budget(clock: Callable[[], float] = monotonic) -> ChartRenderBudget:
    return ChartRenderBudget(started=clock())


def build_scout_report_chart_blocks(
    report: SignalReport,
    run: SignalScoutRun,
    *,
    delivery_id: str | None = None,
    clock: Callable[[], float] = monotonic,
    budget: ChartRenderBudget | None = None,
) -> list[dict]:
    """Render the report's charts to PNGs and return Slack blocks that show them.

    Best effort by design: any chart that cannot be rendered — an unsupported query kind, a
    render failure, no acting user, the cap or the time budget — is skipped rather than failing the
    delivery, since the message still links to the report where the inbox draws every chart. That
    holds for the whole build, not only the render: a chart is a nice-to-have on a message the
    report needs, so anything unexpected here costs the charts rather than the delivery.

    The cap counts attempts, not successes: a report full of failing charts must not launch an
    export workflow per chart. With a `delivery_id`, successful renders are remembered so a retry
    of the same delivery reuses them. Pass a `budget` to spend a render allowance opened before
    this call — a delivery that rebuilds shares one budget across both builds instead of handing
    the rebuild a fresh clock and a fresh set of renders."""
    try:
        return _build_scout_report_chart_blocks(report, run, delivery_id=delivery_id, clock=clock, budget=budget)
    except Exception:
        logger.warning("signals_scout.slack_report_chart_build_error", report_id=str(report.id), exc_info=True)
        return []


def _build_scout_report_chart_blocks(
    report: SignalReport,
    run: SignalScoutRun,
    *,
    delivery_id: str | None,
    clock: Callable[[], float],
    budget: ChartRenderBudget | None,
) -> list[dict]:
    from products.exports.backend.facade.api import RENDER_TIMEOUT, get_delivery_image_url  # noqa: PLC0415

    charts = _ordered_charts(report)
    if not charts:
        return []
    created_by = _acting_user(run, report.team)
    if created_by is None:
        logger.info("signals_scout.slack_report_chart_no_acting_user", report_id=str(report.id), run_id=str(run.id))
        return []

    cache_key = _rendered_assets_cache_key(delivery_id) if delivery_id else None
    budget = new_chart_render_budget(clock) if budget is None else budget
    # This delivery's own renders are authoritative; the retry cache only fills in what an earlier
    # attempt of the same delivery rendered.
    rendered_assets = budget.rendered_assets
    for entry_key, cached_asset_id in _load_rendered_assets(cache_key).items():
        rendered_assets.setdefault(entry_key, cached_asset_id)
    blocks: list[dict] = []
    shown = 0
    for chart in charts:
        if shown >= MAX_SLACK_REPORT_CHARTS:
            break
        query = chart.get("query")
        if not isinstance(query, dict) or query.get("kind") not in _RENDERABLE_CHART_KINDS:
            continue
        chart_id = str(chart.get("chart_id"))
        entry_key = _rendered_asset_entry_key(chart_id, query)
        asset_id = rendered_assets.get(entry_key)
        if asset_id is None:
            if (
                budget.renders_remaining > 0
                and clock() - budget.started + RENDER_TIMEOUT.total_seconds() > SLACK_REPORT_CHART_RENDER_BUDGET_SECONDS
            ):
                logger.info("signals_scout.slack_report_chart_budget_exhausted", report_id=str(report.id))
                budget.renders_remaining = 0
            # Out of renders or out of time, but a later chart may still be in the delivery's cache
            # from an earlier build, so keep looking rather than dropping the rest of the message's
            # charts.
            if budget.renders_remaining <= 0:
                continue
            budget.renders_remaining -= 1
        shown += 1
        try:
            if asset_id is None:
                asset_id = _render_chart_asset_id(team=report.team, created_by=created_by, query=query)
                if asset_id is None:
                    continue
                rendered_assets[entry_key] = asset_id
                # Persist each render as it lands: the delivery task acks late, so a retry after a
                # worker loss mid-delivery must find the renders that had already finished.
                _store_rendered_assets(cache_key, rendered_assets)
            # A cache-hit asset_id comes from the shared retry cache, so pin the URL mint to the
            # acting user: a tampered entry pointing at another same-team user's PNG mints nothing.
            image_url = get_delivery_image_url(
                team_id=report.team_id,
                asset_id=asset_id,
                expiry_delta=SLACK_REPORT_CHART_URL_TTL,
                created_by_id=created_by.id,
            )
        except Exception:
            logger.warning(
                "signals_scout.slack_report_chart_render_error",
                report_id=str(report.id),
                chart_id=chart_id,
                exc_info=True,
            )
            continue
        if image_url is None:
            continue
        blocks.extend(_chart_blocks(chart, image_url, shown))
    return blocks
