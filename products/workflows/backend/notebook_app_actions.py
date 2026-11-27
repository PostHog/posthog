from products.authorization.backend.facade.contracts import Resource
from products.authorization.backend.facade.enums import ResourceType
from products.authorization.backend.presentation.querysets import filter_queryset
from products.workflows.backend.models import HogFlow


def _runnable_workflows(team_id: int, workflow_ids: set[str]) -> set[str]:
    targets = HogFlow.objects.filter(
        team_id=team_id, id__in=workflow_ids, status=HogFlow.State.ACTIVE, trigger__type__in=("manual", "schedule")
    )
    visible = filter_queryset(targets, resource=Resource(type=ResourceType.HOG_FLOW, project_id=team_id))
    return {str(pk) for pk in visible.values_list("id", flat=True)}


TARGET_PROVIDERS = {"run_workflow": _runnable_workflows}
