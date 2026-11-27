from products.workflows.backend.models import HogFlow


def _runnable_workflows(team_id: int, workflow_ids: set[str]) -> list[tuple[str, int | None]]:
    targets = HogFlow.objects.filter(
        team_id=team_id, id__in=workflow_ids, status=HogFlow.State.ACTIVE, trigger__type__in=("manual", "schedule")
    )
    return [(str(pk), creator) for pk, creator in targets.values_list("id", "created_by_id")]


TARGET_PROVIDERS = {"run_workflow": _runnable_workflows}
