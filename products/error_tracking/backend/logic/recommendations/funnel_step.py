import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from posthog.schema import ProductKey

from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen

from .flow_attach import AttachTarget, linked_issues
from .impact_lens import MAX_ISSUES, WINDOW_HOURS, ImpactLens
from .page_flows import (
    MIN_BASELINE_DAYS,
    MIN_STARTS,
    Chain,
    EvaluationWindow,
    Flow,
    HourlyStats,
    baseline,
    baseline_days,
    fetch_page_flows,
    fetch_step_hours,
    incident_counts,
    is_evaluable,
    is_surge,
    merge_drop_hours,
    worst_hour,
)

# A chain's rate is the product of its step rates and often sits under 20%, so a drop is measured against the usual
# rate rather than in points.
MAX_DROP_RATIO = 0.7
MIN_DROP_Z = 4.0
# A step's own rate counts only with this many visits entering the step, in the hour and on each usual day.
MIN_STEP_ENTRANTS = 30
# The broken step is clear when its rate fell below this share of its usual rate and every other step held.
CLEAR_STEP_RATIO = 0.75
HOLDING_STEP_RATIO = 0.9
# A chain that drops this often in the last weeks is unstable, so its drops are not shown.
MUTE_DAYS = 21
MAX_INCIDENTS_BEFORE_MUTE = 3
MAX_INCIDENTS = 10


@frozen
class StepChange:
    """One step of a chain in an hour: how many visits entered and continued, against the step's usual rate."""

    flow: Flow
    entered: int
    continued: int
    usual_rate: float | None

    @property
    def rate(self) -> float | None:
        return self.continued / self.entered if self.entered else None

    @property
    def ratio(self) -> float | None:
        """The step's rate against its usual rate, when both have enough visits to judge."""
        if self.entered < MIN_STEP_ENTRANTS or self.usual_rate is None or self.usual_rate == 0:
            return None
        return self.continued / self.entered / self.usual_rate


@frozen
class BrokenStep:
    index: int
    # The step fell far below its usual rate and every other step that can be judged held.
    clear: bool


def find_chain_drop_hours(hours: HourlyStats, window: EvaluationWindow) -> list[datetime]:
    """Hours in the window whose share of visits through the whole chain fell far below the same hour on the previous
    days, by at least MIN_DROP_Z standard errors."""
    drops = []
    for hour, counts in sorted(hours.items()):
        if hour not in window or counts.starts < MIN_STARTS:
            continue
        usual = baseline(hours, hour)
        if usual is None:
            continue
        rate = counts.finishes / counts.starts
        z = (usual.rate - rate) / math.sqrt(max(usual.rate * (1 - usual.rate), 1e-9) / counts.starts)
        if rate < MAX_DROP_RATIO * usual.rate and z >= MIN_DROP_Z:
            drops.append(hour)
    return drops


def step_changes(chain: Chain, hours: HourlyStats, hour: datetime) -> list[StepChange]:
    """Each step of the chain in ``hour``, with the median of its own rate at that hour on the previous days."""
    reached = hours[hour].reached
    changes = []
    for step, flow in enumerate(chain.steps):
        days = baseline_days(hours, hour, enough=MIN_STEP_ENTRANTS, step=step)
        changes.append(
            StepChange(
                flow=flow,
                entered=reached[step],
                continued=reached[step + 1],
                usual_rate=statistics.median(day.reached[step + 1] / day.reached[step] for day in days)
                if len(days) >= MIN_BASELINE_DAYS
                else None,
            )
        )
    return changes


def find_broken_step(changes: list[StepChange]) -> BrokenStep | None:
    """The step with the lowest rate against its usual rate. Steps without enough visits to judge are left out."""
    measured = [(change.ratio, index) for index, change in enumerate(changes) if change.ratio is not None]
    if not measured:
        return None
    lowest, index = min(measured)
    return BrokenStep(
        index=index,
        clear=lowest < CLEAR_STEP_RATIO
        and all(ratio >= HOLDING_STEP_RATIO for ratio, other in measured if other != index),
    )


def count_incidents(hours: HourlyStats, window: EvaluationWindow) -> int:
    """The chain's drops in the window, leaving out drops from extra traffic."""
    return sum(1 for drop in merge_drop_hours(find_chain_drop_hours(hours, window)) if not is_surge(hours, drop))


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def chain_incident(chain: Chain, hours: HourlyStats, drop: list[datetime], window: EvaluationWindow) -> dict[str, Any]:
    """The incident as shown: the whole chain's worst hour against usual, and each step's own rate against usual."""
    worst = worst_hour(hours, drop)
    reached = hours[worst].reached
    usual_days = baseline_days(hours, worst)
    changes = step_changes(chain, hours, worst)
    broken = find_broken_step(changes)
    return {
        "pages": list(chain.pages),
        **incident_counts(hours, drop, window),
        "steps": [
            {
                "from_path": change.flow.from_path,
                "to_path": change.flow.to_path,
                "entered": change.entered,
                "continued": change.continued,
                "rate": _round(change.rate),
                "usual_rate": _round(change.usual_rate),
                "ratio": _round(change.ratio),
                # The share of the chain's visits that got this far, for drawing the chain as a funnel.
                "reached_rate": round(reached[step + 1] / reached[0], 4),
                "usual_reached_rate": round(
                    statistics.median(day.reached[step + 1] / day.reached[0] for day in usual_days), 4
                ),
            }
            for step, change in enumerate(changes)
        ],
        "broken_step": broken.index if broken else None,
        "clear": broken.clear if broken else False,
    }


def muted_chains(incident_chains: dict[int, list[Chain]], window: EvaluationWindow) -> dict[tuple[int, Chain], int]:
    """The chains that dropped more than MAX_INCIDENTS_BEFORE_MUTE times in the last MUTE_DAYS, with their count.

    Reads the weeks before the window only for chains that dropped in it, which is rare.
    """
    mute_window = EvaluationWindow(
        first_hour=window.last_hour - timedelta(days=MUTE_DAYS) + timedelta(hours=1), last_hour=window.last_hour
    )
    hours = fetch_step_hours(
        {team_id: [chain.pages for chain in chains] for team_id, chains in incident_chains.items()},
        mute_window.history_since,
        window.read_until,
    )
    muted = {}
    for team_id, chains in incident_chains.items():
        for index, chain in enumerate(chains):
            count = count_incidents(hours.get((team_id, index), {}), mute_window)
            if count > MAX_INCIDENTS_BEFORE_MUTE:
                muted[(team_id, chain)] = count
    return muted


class FunnelStepRecommendation(ImpactLens):
    type = "funnel_step"
    refresh_interval = timedelta(hours=1)
    # Shares its pageview read with Broken flow, so both go stale together and the sweep reads it once.
    refresh_group = "page_flows"

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:funnel_step",
        )
        window = EvaluationWindow.ending_before(timezone.now())
        page_flows = fetch_page_flows(team_ids, window)
        metas: dict[int, dict[str, Any]] = {}
        drops: list[tuple[int, Chain, list[datetime]]] = []
        for team_id in team_ids:
            team_flows = page_flows[team_id]
            surges = []
            for chain, hours in zip(team_flows.chains, team_flows.chain_hours):
                for drop in merge_drop_hours(find_chain_drop_hours(hours, window)):
                    if is_surge(hours, drop):
                        surges.append(chain_incident(chain, hours, drop, window))
                    else:
                        drops.append((team_id, chain, drop))
            metas[team_id] = {
                "window_hours": WINDOW_HOURS,
                "first_hour": window.first_hour.isoformat(),
                "last_hour": window.last_hour.isoformat(),
                "evaluable": any(is_evaluable(hours, window) for hours in team_flows.chain_hours),
                "chains": [list(chain.pages) for chain in team_flows.chains],
                "incidents": [],
                "surges": sorted(surges, key=lambda i: i["hour"], reverse=True)[:MAX_INCIDENTS],
                "muted": [],
                "issues": [],
            }
        if not drops:
            return metas

        incident_chains: dict[int, list[Chain]] = defaultdict(list)
        for team_id, chain, _ in drops:
            if chain not in incident_chains[team_id]:
                incident_chains[team_id].append(chain)
        muted = muted_chains(incident_chains, window)
        for (team_id, chain), count in muted.items():
            metas[team_id]["muted"].append({"pages": list(chain.pages), "incidents": count})

        incidents: list[tuple[int, dict[str, Any]]] = []
        tested: list[tuple[int, dict[str, Any], AttachTarget]] = []
        for team_id, chain, drop in drops:
            if (team_id, chain) in muted:
                continue
            hours = page_flows[team_id].chain_hours[page_flows[team_id].chains.index(chain)]
            incident = {**chain_incident(chain, hours, drop, window), "issues": []}
            incidents.append((team_id, incident))
            # Errors are tested on the start page of the step that broke, the way Broken flow tests a two-page flow.
            if incident["broken_step"] is not None:
                target = AttachTarget(
                    team_id=team_id,
                    hour=datetime.fromisoformat(incident["worst_hour"]),
                    flow=chain.steps[incident["broken_step"]],
                )
                tested.append((team_id, incident, target))

        flattened: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
        for (team_id, incident, _), issues in zip(tested, linked_issues([target for *_, target in tested], window)):
            incident["issues"] = issues
            step = incident["steps"][incident["broken_step"]]
            for issue in issues:
                previous = flattened[team_id].get(issue["id"])
                if previous is None or issue["exposed"] > previous["exposed"]:
                    flattened[team_id][issue["id"]] = {
                        **issue,
                        "pages": incident["pages"],
                        "hour": incident["hour"],
                        "broken_step": incident["broken_step"],
                        "from_path": step["from_path"],
                        "to_path": step["to_path"],
                        "rate": incident["rate"],
                        "usual_rate": incident["usual_rate"],
                    }

        for team_id, incident in incidents:
            metas[team_id]["incidents"].append(incident)
        for team_id in team_ids:
            metas[team_id]["incidents"] = sorted(metas[team_id]["incidents"], key=lambda i: i["hour"], reverse=True)[
                :MAX_INCIDENTS
            ]
            metas[team_id]["issues"] = sorted(flattened[team_id].values(), key=lambda i: -i["exposed"])[:MAX_ISSUES]
        return metas
