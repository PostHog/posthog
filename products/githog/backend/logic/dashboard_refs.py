"""Find saved insights and dashboards that reference flag keys / event names.

This is the "this PR touches the homepage funnel" signal. Given the set of
keys/names that appear in the PR, we look for any saved insight whose
filters / query JSON, name, or derived name contains a match, then walk
the dashboard tiles to surface containing dashboards.

The match is a coarse substring check against the cast-to-text JSON
columns — imperfect, but cheap, and good enough to flag the dashboards
a reviewer would care about. False positives are mostly harmless (a
dashboard name happens to share a token); false negatives only happen
for very short / common keys, which we already filter out below.
"""

from typing import TYPE_CHECKING

from django.db.models import Q, TextField
from django.db.models.functions import Cast

from posthog.models import Insight

from products.dashboards.backend.models.dashboard_tile import DashboardTile

if TYPE_CHECKING:
    from posthog.models import Team

    from ..facade.contracts import DashboardReference


# Short / generic terms produce noisy matches against unrelated JSON. Mirrors
# the floor used by the known-key diff scanner.
_MIN_TERM_LEN = 4

# Caps to keep the response payload bounded for the demo widget.
_MAX_INSIGHTS = 50
_MAX_DASHBOARDS = 25


def find_referencing_insights_and_dashboards(
    team: "Team",
    terms: list[str],
) -> list["DashboardReference"]:
    """Return a list of DashboardReference, insights first, then dashboards.

    Each reference carries the set of terms that caused the match, so the
    UI can show *why* a given surface is implicated.
    """
    from ..facade.contracts import DashboardReference

    search_terms = sorted({t for t in terms if t and len(t) >= _MIN_TERM_LEN})
    if not search_terms:
        return []

    # OR across the terms, applied to the text-cast filters/query plus the
    # name/derived_name columns. One query, all matches.
    q = Q()
    for term in search_terms:
        q |= (
            Q(filters_text__icontains=term)
            | Q(query_text__icontains=term)
            | Q(name__icontains=term)
            | Q(derived_name__icontains=term)
        )

    insights = list(
        Insight.objects.filter(team=team, deleted=False)
        .annotate(
            filters_text=Cast("filters", output_field=TextField()),
            query_text=Cast("query", output_field=TextField()),
        )
        .filter(q)
        .order_by("-last_modified_at", "-id")[:_MAX_INSIGHTS]
    )

    # Recompute the per-insight matched terms in Python — DB query gives us
    # "matched at least one," not "which one." This is cheap: at most
    # 50 insights × N terms substring checks.
    matched_by_insight: dict[int, set[str]] = {}
    insight_refs: list[DashboardReference] = []
    for insight in insights:
        haystack = " ".join(
            filter(
                None,
                [
                    str(insight.filters or ""),
                    str(insight.query or ""),
                    insight.name or "",
                    insight.derived_name or "",
                ],
            )
        )
        matches = {t for t in search_terms if t in haystack}
        if not matches:
            continue
        matched_by_insight[insight.id] = matches
        insight_refs.append(
            DashboardReference(
                kind="insight",
                id=insight.id,
                name=insight.name or insight.derived_name or "Untitled insight",
                short_id=insight.short_id,
                matched_keys=tuple(sorted(matches)),
            )
        )

    # Walk dashboard tiles to find dashboards whose insights matched. Aggregate
    # the matched terms across all of a dashboard's matching insights.
    dashboard_refs: list[DashboardReference] = []
    if matched_by_insight:
        tiles = (
            DashboardTile.objects.filter(
                insight_id__in=matched_by_insight.keys(),
                dashboard__team=team,
                dashboard__deleted=False,
            )
            .select_related("dashboard")
            .only("insight_id", "dashboard__id", "dashboard__name")
        )
        by_dashboard: dict[int, tuple[str, set[str]]] = {}
        for tile in tiles:
            dashboard = tile.dashboard
            terms_for_insight = matched_by_insight.get(tile.insight_id, set())
            if not terms_for_insight:
                continue
            existing = by_dashboard.get(dashboard.id)
            if existing is None:
                by_dashboard[dashboard.id] = (dashboard.name or "Untitled dashboard", set(terms_for_insight))
            else:
                existing[1].update(terms_for_insight)

        for dashboard_id, (name, term_set) in list(by_dashboard.items())[:_MAX_DASHBOARDS]:
            dashboard_refs.append(
                DashboardReference(
                    kind="dashboard",
                    id=dashboard_id,
                    name=name,
                    short_id=None,
                    matched_keys=tuple(sorted(term_set)),
                )
            )

    # Dashboards first — they're the headline signal — then individual insights.
    return dashboard_refs + insight_refs
