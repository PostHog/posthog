"""Actor properties shared by the signals analytics events that record who acted on a report.

`signal_report_status_changed` and `signals_report_claimed` both send the project as their distinct id,
so these properties are what ties the event to the person, their agent, or the task behind it.
"""

from __future__ import annotations

from typing import Any

from posthog.models.user import User

from products.signals.backend.artefact_attribution import ArtefactAttribution


def actor_properties(
    actor: ArtefactAttribution | None, actor_user: User | None = None, credited_user: User | None = None
) -> dict[str, Any]:
    """Actor properties for an analytics event. An action with no caller-set actor is `system`.

    An actor without a user, such as the PR-merge resolve, keeps its kind and names `credited_user`, so
    the person counts as active while the ranking labels still read the transition as automatic.
    """
    actor = actor or ArtefactAttribution.system()
    properties: dict[str, Any] = {
        "actor_kind": actor.kind,
        "actor_user_uuid": None,
        "actor_distinct_id": None,
        "actor_agent": actor.agent_name,
        "actor_task_id": actor.task_id,
    }
    if actor.user_id is None:
        if credited_user is not None:
            properties["actor_user_uuid"] = str(credited_user.uuid)
            properties["actor_distinct_id"] = credited_user.distinct_id
        return properties
    # Callers that already loaded the actor's user pass it to skip a repeat lookup, such as the
    # bulk-state endpoint, which transitions up to 100 reports for one actor.
    if actor_user is not None and actor_user.id == actor.user_id:
        properties["actor_user_uuid"] = str(actor_user.uuid)
        properties["actor_distinct_id"] = actor_user.distinct_id
        return properties
    user = User.objects.filter(id=actor.user_id).values("uuid", "distinct_id").first()
    if user is not None:
        properties["actor_user_uuid"] = str(user["uuid"])
        properties["actor_distinct_id"] = user["distinct_id"]
    return properties
