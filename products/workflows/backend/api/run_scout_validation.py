"""Save-time guards for workflows containing a "Run scout" action.

Two failure modes are specific to this action and cheap to rule out before a flow ever runs, so
both are enforced when the flow is saved rather than left to the engine:

1. **Flood.** An event trigger can fire hundreds of times an hour, and each fire is an LLM sandbox
   run. Signals applies its own 30-minute cooldown as a backstop it doesn't have to trust anyone
   for, but that turns a misconfigured flow into a stream of skipped steps rather than something
   the author notices. Requiring trigger masking puts the first line of defence where the author
   can see it.
2. **Self-loop.** A scout run writes events into the team's own project, which land on the main
   events topic — so a flow triggered on one of those events, which then runs a scout, retriggers
   itself. Masking and the cooldown blunt a tight loop but not a cadence-spaced one.

Both checks are deliberately narrow: they reject configurations that are loops or floods by
construction, and say exactly what to change. Anything requiring the engine to reason about what
an event *will* match at runtime stays out of here.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from products.signals.backend.facade.api import SCOUT_EMITTED_EVENTS

RUN_SCOUT_TEMPLATE_ID = "template-posthog-run-scout"


def flow_runs_a_scout(actions: list[dict]) -> bool:
    """Whether any action in the flow is a "Run scout" node. It's a plain `function` action with
    this template id, which is why no action-type registry knows about this feature."""
    return any(
        action.get("type") == "function" and (action.get("config") or {}).get("template_id") == RUN_SCOUT_TEMPLATE_ID
        for action in actions
        if isinstance(action, dict)
    )


def _trigger_event_ids(trigger_config: dict) -> list[str]:
    """Event names the trigger's `events` entries name, as authored."""
    filters = trigger_config.get("filters") or {}
    return [
        str(entry.get("id"))
        for entry in (filters.get("events") or [])
        if isinstance(entry, dict) and entry.get("id") is not None
    ]


def _trigger_is_unfiltered(trigger_config: dict) -> bool:
    """Whether the trigger names no event and no action, i.e. it matches the whole event stream —
    scout-emitted events included."""
    filters = trigger_config.get("filters") or {}
    return not (filters.get("events") or filters.get("actions"))


def validate_run_scout_flow(*, actions: list[dict], trigger_config: dict[str, Any], trigger_masking: Any) -> None:
    """Raise `ValidationError` when an event-triggered flow with a "Run scout" node is unsafe.

    No-op for a flow without a run-scout node, and for one whose trigger isn't event-based (a
    scheduled or manual flow fires at a rate its author picked, and can't be fed by the scout's own
    output).
    """
    if trigger_config.get("type") != "event" or not flow_runs_a_scout(actions):
        return

    errors: list[str] = []

    if not trigger_masking:
        errors.append(
            "An event-triggered workflow that runs a scout needs trigger masking, so a burst of "
            "matching events can't start a burst of scout runs. Set a masking hash and TTL on the "
            "workflow (a constant hash such as '\\'run-scout\\'' with a 30-minute TTL fires the "
            "workflow at most once per window)."
        )

    scout_events = sorted(set(_trigger_event_ids(trigger_config)) & SCOUT_EMITTED_EVENTS)
    if scout_events:
        errors.append(
            f"This workflow runs a scout and is triggered by {', '.join(scout_events)}, which is an "
            "event scouts themselves emit — each run would retrigger the workflow. Trigger it on "
            "something a scout does not produce."
        )
    elif _trigger_is_unfiltered(trigger_config):
        errors.append(
            "This workflow runs a scout but its trigger matches every event, including the "
            f"{', '.join(sorted(SCOUT_EMITTED_EVENTS))} events scouts emit — each run would "
            "retrigger the workflow. Narrow the trigger to the events you actually want to act on."
        )

    if errors:
        raise serializers.ValidationError({"actions": errors})
