from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from posthog.schema import ProductKey

from posthog.clickhouse.query_tagging import Feature, tag_queries

from .flow_attach import AttachTarget, linked_issues
from .impact_lens import MAX_ISSUES, WINDOW_HOURS, ImpactLens
from .page_flows import (
    MIN_STARTS,
    EvaluationWindow,
    Flow,
    HourlyStats,
    baseline,
    fetch_page_flows,
    incident_counts,
    is_evaluable,
    is_surge,
    merge_drop_hours,
)

MIN_DROP = 0.08
MAX_DROP_RATIO = 0.75
MAX_INCIDENTS = 10


def find_drop_hours(hours: HourlyStats, window: EvaluationWindow) -> list[datetime]:
    """Hours in the window whose success rate fell far below the same hour on the previous days."""
    drops = []
    for hour, counts in sorted(hours.items()):
        if hour not in window or counts.starts < MIN_STARTS:
            continue
        usual = baseline(hours, hour)
        if usual is None:
            continue
        rate = counts.finishes / counts.starts
        if rate <= usual.rate - MIN_DROP and rate < MAX_DROP_RATIO * usual.rate:
            drops.append(hour)
    return drops


class FlowDropRecommendation(ImpactLens):
    type = "flow_drop"
    refresh_interval = timedelta(hours=1)
    # Shares its pageview read with Broken funnel step, so both go stale together and the sweep reads it once.
    refresh_group = "page_flows"

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:flow_drop",
        )
        window = EvaluationWindow.ending_before(timezone.now())
        page_flows = fetch_page_flows(team_ids, window)
        metas: dict[int, dict[str, Any]] = {}
        incidents: list[tuple[int, Flow, dict[str, Any]]] = []
        for team_id in team_ids:
            team_flows = page_flows[team_id]
            surges = []
            for flow, hours in zip(team_flows.flows, team_flows.flow_hours):
                for drop in merge_drop_hours(find_drop_hours(hours, window)):
                    incident = {
                        "from_path": flow.from_path,
                        "to_path": flow.to_path,
                        **incident_counts(hours, drop, window),
                    }
                    if is_surge(hours, drop):
                        surges.append(incident)
                    else:
                        incidents.append((team_id, flow, {**incident, "issues": []}))
            metas[team_id] = {
                "window_hours": WINDOW_HOURS,
                "first_hour": window.first_hour.isoformat(),
                "last_hour": window.last_hour.isoformat(),
                "evaluable": any(is_evaluable(hours, window) for hours in team_flows.flow_hours),
                "flows": [{"from_path": flow.from_path, "to_path": flow.to_path} for flow in team_flows.flows],
                "incidents": [],
                "surges": sorted(surges, key=lambda i: i["hour"], reverse=True)[:MAX_INCIDENTS],
                "issues": [],
            }

        linked = linked_issues(
            [
                AttachTarget(team_id=team_id, hour=datetime.fromisoformat(incident["worst_hour"]), flow=flow)
                for team_id, flow, incident in incidents
            ],
            window,
        )
        flattened: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
        for (team_id, _, incident), issues in zip(incidents, linked):
            incident["issues"] = issues
            for issue in issues:
                previous = flattened[team_id].get(issue["id"])
                if previous is None or issue["exposed"] > previous["exposed"]:
                    flattened[team_id][issue["id"]] = {
                        **issue,
                        "from_path": incident["from_path"],
                        "to_path": incident["to_path"],
                        "hour": incident["hour"],
                        "rate": incident["rate"],
                        "usual_rate": incident["usual_rate"],
                    }
            metas[team_id]["incidents"].append(incident)

        for team_id in team_ids:
            metas[team_id]["incidents"] = sorted(metas[team_id]["incidents"], key=lambda i: i["hour"], reverse=True)[
                :MAX_INCIDENTS
            ]
            metas[team_id]["issues"] = sorted(flattened[team_id].values(), key=lambda i: -i["exposed"])[:MAX_ISSUES]
        return metas
