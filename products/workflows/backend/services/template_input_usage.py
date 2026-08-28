"""Find workflows (HogFlows) that reference a given function-template input by its keys.

Generic, template-agnostic counterpart to ``integration_usage.py``: the caller supplies the
``template_id`` and the dictionary ``input_key`` to inspect, and gets back, per key found, the
workflows that set it. Used (e.g.) to surface which workflows reference a custom property
definition via the "Update account property" action's ``properties`` input.
"""

from dataclasses import dataclass

from products.workflows.backend.models import HogFlow


@dataclass(frozen=True)
class HogFlowReference:
    id: str
    name: str
    status: str


def get_hog_flows_referencing_template_input_keys(
    team_id: int, template_id: str, input_key: str, *, only_value_key: str | None = None
) -> dict[str, list[HogFlowReference]]:
    """Map each key present in ``input_key``'s dict (across the team's workflows) to the workflows
    that set it.

    Scans every saved workflow for the team (all statuses), looking at ``function`` actions whose
    ``config.template_id`` matches ``template_id`` and reading the dict stored at
    ``config.inputs[input_key].value``. Keys prefixed with ``$$_`` (templating internals like
    ``$$_extend_object``) are ignored.

    When ``only_value_key`` is given, the scan collects references for just that one key (the
    single-definition lookup path) instead of building the full map.
    """
    references: dict[str, list[HogFlowReference]] = {}
    # Project to only the columns the scanner reads — the rest (trigger, edges, draft, …) are unused.
    for flow in HogFlow.objects.filter(team_id=team_id).only("id", "name", "status", "actions"):
        ref: HogFlowReference | None = None
        for key in _referenced_keys(flow.actions or [], template_id, input_key, only_value_key=only_value_key):
            if ref is None:
                ref = HogFlowReference(id=str(flow.id), name=flow.name or str(flow.id), status=flow.status)
            references.setdefault(key, []).append(ref)
    return references


def _referenced_keys(
    actions: list[dict], template_id: str, input_key: str, *, only_value_key: str | None = None
) -> set[str]:
    keys: set[str] = set()
    for action in actions:
        if action.get("type") != "function":
            continue
        config = action.get("config") or {}
        if config.get("template_id") != template_id:
            continue
        value = ((config.get("inputs") or {}).get(input_key) or {}).get("value")
        if isinstance(value, dict):
            keys.update(
                key
                for key in value
                if not (isinstance(key, str) and key.startswith("$$_"))
                and (only_value_key is None or key == only_value_key)
            )
    return keys
