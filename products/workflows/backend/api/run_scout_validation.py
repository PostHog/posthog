"""Save-time guards for workflows containing a "Run scout" action.

Three failure modes are specific to this action and cheap to rule out before a flow ever runs, so
they are enforced when the flow is saved rather than left to the engine:

1. **Flood.** Every trigger except a schedule or a manual press fires once per occurrence: an
   event, a batch audience member, a warehouse row, a Slack message. Each fire is an LLM sandbox
   run. Signals applies its own 30-minute cooldown as a backstop it doesn't have to trust anyone
   for, but that turns a misconfigured flow into a stream of skipped steps rather than something
   the author notices. Requiring trigger masking that fires the flow at most once per window puts
   the first line of defence where the author can see it. Webhook and tracking pixel triggers
   never pass through the masker, so the node is refused on those outright.
2. **Self-loop.** A scout run writes events into the team's own project, which land on the main
   events topic — so a flow triggered on one of those events, which then runs a scout, retriggers
   itself. Masking and the cooldown blunt a tight loop but not a cadence-spaced one.
3. **Environment.** Scouts belong to the project's main environment, and the run endpoint is
   called by a service token with no human credential left to re-check against that environment.
   A workflow saved in a child environment is therefore refused rather than resolved upwards.

All checks are deliberately narrow: they reject configurations that are loops or floods by
construction, and say exactly what to change. Anything requiring the engine to reason about what
an event *will* match at runtime stays out of here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rest_framework import serializers

from products.actions.backend.models import Action
from products.signals.backend.facade.api import SCOUT_EMITTED_EVENTS, WORKFLOW_RUN_COOLDOWN_S

if TYPE_CHECKING:
    from posthog.models import Team

RUN_SCOUT_TEMPLATE_ID = "template-posthog-run-scout"

# Fire once per author-chosen occasion, so neither the flood nor the loop guard applies.
_SINGLE_FIRE_TRIGGERS = frozenset({"schedule", "manual"})
# Built into an invocation directly by the source webhooks consumer, which never consults the
# masker, so masking cannot throttle them.
_UNMASKED_TRIGGERS = {"webhook": "webhook", "tracking_pixel": "tracking pixel"}


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


def _trigger_action_ids(trigger_config: dict) -> list[int]:
    """Action ids the trigger's `actions` entries name, as authored. Anything non-numeric is left
    for the filters serializer to reject."""
    filters = trigger_config.get("filters") or {}
    ids: list[int] = []
    for entry in filters.get("actions") or []:
        if not isinstance(entry, dict) or entry.get("id") is None:
            continue
        try:
            ids.append(int(entry["id"]))
        except (TypeError, ValueError):
            continue
    return ids


def _trigger_is_unfiltered(trigger_config: dict) -> bool:
    """Whether the trigger matches the whole event stream, scout-emitted events included: it names
    no event and no action, or one of its event entries has no `id`, which the compiler turns into
    a match-all."""
    filters = trigger_config.get("filters") or {}
    events = filters.get("events") or []
    if any(isinstance(entry, dict) and entry.get("id") is None for entry in events):
        return True
    return not (events or filters.get("actions"))


def _actions_reaching_scout_events(team: Team, action_ids: list[int]) -> list[str]:
    """Names of the project's Actions (among `action_ids`) with a step that can match a
    scout-emitted event: one naming such an event, or one with no event at all, which matches
    every event. Resolved the way the trigger compiler resolves them: across the whole project,
    soft-deleted rows included."""
    if not action_ids:
        return []
    names: list[str] = []
    # nosemgrep: idor-lookup-without-team (scoped by team__project_id, matching posthog/cdp/filters.py)
    for action in Action.objects.filter(team__project_id=team.project_id, id__in=action_ids).order_by("id"):
        if any(step.event is None or step.event in SCOUT_EMITTED_EVENTS for step in action.steps):
            names.append(action.name or str(action.id))
    return names


def _masking_problems(trigger_masking: Any) -> list[str]:
    """Ways a masking config would still let the flow fire more than once per window."""
    if not isinstance(trigger_masking, dict):
        return []
    problems: list[str] = []
    if "{" in str(trigger_masking.get("hash") or ""):
        problems.append("the hash is an expression, so it fires once per distinct value")
    if trigger_masking.get("threshold") is not None:
        problems.append("a threshold samples matches instead of suppressing them")
    ttl = trigger_masking.get("ttl")
    if not isinstance(ttl, int | float) or ttl < WORKFLOW_RUN_COOLDOWN_S:
        problems.append(f"the TTL is under {WORKFLOW_RUN_COOLDOWN_S // 60} minutes")
    return problems


def validate_run_scout_flow(
    *, actions: list[dict], trigger_config: dict[str, Any], trigger_masking: Any, team: Team | None
) -> None:
    """Raise `ValidationError` when a flow with a "Run scout" node is unsafe.

    No-op for a flow without a run-scout node. `team` is needed for the environment check and to
    resolve action-based triggers; without it (a re-save outside a request) both are skipped,
    since the flow already passed them once.
    """
    if not flow_runs_a_scout(actions):
        return

    errors: list[str] = []
    trigger_type = trigger_config.get("type")

    if team is not None and team.parent_team_id:
        errors.append(
            "Running a scout from a workflow is only available in the project's main environment. "
            "Create the workflow there instead."
        )

    if trigger_type in _UNMASKED_TRIGGERS:
        errors.append(
            f"This workflow runs a scout, but a {_UNMASKED_TRIGGERS[trigger_type]} trigger fires it on "
            "every call and trigger masking does not apply to it. Trigger it from an event instead."
        )
    elif trigger_type not in _SINGLE_FIRE_TRIGGERS:
        if not trigger_masking:
            errors.append(
                "A workflow that runs a scout needs trigger masking, so a burst of matching events "
                "can't start a burst of scout runs. Set a masking hash and TTL on the workflow: a "
                f"constant hash such as 'run-scout' (not an expression) with a TTL of at least "
                f"{WORKFLOW_RUN_COOLDOWN_S // 60} minutes fires the workflow at most once per window."
            )
        elif problems := _masking_problems(trigger_masking):
            errors.append(
                "Trigger masking on a workflow that runs a scout has to fire it at most once per "
                f"window, but {'; '.join(problems)}. Use a constant hash such as 'run-scout', no "
                f"threshold, and a TTL of at least {WORKFLOW_RUN_COOLDOWN_S // 60} minutes."
            )

    if trigger_type == "event":
        errors.extend(_loop_problems(trigger_config, team))

    if errors:
        raise serializers.ValidationError({"actions": errors})


def _loop_problems(trigger_config: dict[str, Any], team: Team | None) -> list[str]:
    """Ways an event trigger could be satisfied by the events a scout run emits."""
    scout_events = sorted(set(_trigger_event_ids(trigger_config)) & SCOUT_EMITTED_EVENTS)
    if scout_events:
        return [
            f"This workflow runs a scout and is triggered by {', '.join(scout_events)}, which is an "
            "event scouts themselves emit, so each run would retrigger the workflow. Trigger it on "
            "something a scout does not produce."
        ]
    if _trigger_is_unfiltered(trigger_config):
        return [
            "This workflow runs a scout but its trigger matches every event, including the "
            f"{', '.join(sorted(SCOUT_EMITTED_EVENTS))} events scouts emit, so each run would "
            "retrigger the workflow. Narrow the trigger to the events you actually want to act on."
        ]
    if team is None:
        return []
    # An Action is only as narrow as its steps: a step naming a scout event, or one with no
    # event (which matches everything), lets scout output back into the trigger.
    looping_actions = _actions_reaching_scout_events(team, _trigger_action_ids(trigger_config))
    if not looping_actions:
        return []
    return [
        f"This workflow runs a scout and is triggered by the action(s) {', '.join(looping_actions)}, "
        "which can match an event scouts themselves emit (a step with no event matches every "
        "event), so each run would retrigger the workflow. Give every step of the action an event "
        "a scout does not produce."
    ]
