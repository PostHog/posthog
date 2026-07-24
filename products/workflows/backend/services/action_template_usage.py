"""Find workflows (HogFlows) that link to saved action templates.

Counterpart to ``template_input_usage.py`` for the reusable action template feature: workflow
``function`` actions reference a ``HogFlowActionTemplate`` row via ``config.action_template_id``.
Used to power usage counts in the library UI and to block deleting a template that is still
linked from a workflow.
"""

from dataclasses import dataclass

from products.workflows.backend.models import HogFlow


@dataclass(frozen=True)
class HogFlowReference:
    id: str
    name: str
    status: str


def get_hog_flows_referencing_action_templates(
    team_id: int, template_ids: list[str] | None = None
) -> dict[str, list[HogFlowReference]]:
    """Map each referenced action template id to the workflows that link to it.

    Scans every non-archived workflow for the team, looking at ``function`` actions with an
    ``action_template_id`` in both the live ``actions`` and any pending ``draft`` actions — a
    draft-only reference still becomes live on publish, so it must count as usage.

    When ``template_ids`` is given, only references to those ids are collected; otherwise the
    full per-template map is built (the list endpoint's usage counts).
    """
    wanted = set(template_ids) if template_ids is not None else None
    references: dict[str, list[HogFlowReference]] = {}
    for flow in (
        HogFlow.objects.filter(team_id=team_id)
        .exclude(status=HogFlow.State.ARCHIVED)
        .only("id", "name", "status", "actions", "draft")
    ):
        draft_actions = (flow.draft or {}).get("actions") or []
        referenced = _referenced_template_ids(flow.actions or [], wanted) | _referenced_template_ids(
            draft_actions, wanted
        )
        if not referenced:
            continue
        ref = HogFlowReference(id=str(flow.id), name=flow.name or str(flow.id), status=flow.status)
        for template_id in referenced:
            references.setdefault(template_id, []).append(ref)
    return references


def _referenced_template_ids(actions: list[dict], wanted: set[str] | None) -> set[str]:
    referenced: set[str] = set()
    for action in actions:
        if not isinstance(action, dict) or action.get("type") != "function":
            continue
        template_id = (action.get("config") or {}).get("action_template_id")
        if isinstance(template_id, str) and template_id and (wanted is None or template_id in wanted):
            referenced.add(template_id)
    return referenced
