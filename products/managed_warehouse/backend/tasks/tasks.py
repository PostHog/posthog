from celery import shared_task

from posthog.tasks.utils import CeleryQueue

from products.managed_warehouse.backend.internal_loading import load_internal_team


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=300,
    max_retries=72,
)
def load_internal_warehouse(organization_id: str, team_id: int, generation: int) -> None:
    load_internal_team(organization_id, team_id, generation)


# Member-team pushes retry for about ten hours: a removal must reach hogtower, because hogtower
# revokes the member's team credentials only when it does.
_MEMBER_TEAMS_RETRY = {
    "autoretry_for": (Exception,),
    "retry_backoff": 30,
    "retry_backoff_max": 600,
    "max_retries": 60,
}


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value, **_MEMBER_TEAMS_RETRY)
def push_warehouse_member_teams(organization_id: str, user_uuid: str) -> None:
    from products.managed_warehouse.backend import member_teams  # noqa: PLC0415

    if member_teams.is_enabled():
        member_teams.push_member(organization_id, user_uuid)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value, **_MEMBER_TEAMS_RETRY)
def push_warehouse_organization_member_teams(organization_id: str) -> None:
    from products.managed_warehouse.backend import member_teams  # noqa: PLC0415

    if member_teams.is_enabled():
        member_teams.push_organization(organization_id)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def push_all_warehouse_member_teams() -> None:
    from products.managed_warehouse.backend import member_teams  # noqa: PLC0415

    if member_teams.is_enabled():
        member_teams.push_all()


# Long-running: an explain run plans one batch of a team's models on Trino, one after another.
# acks_late and reject_on_worker_lost make the broker deliver a batch again when a deploy replaces the worker
# before the batch finishes. The check only reads, so checking a batch twice is safe.
# The soft time limit stays below the Redis visibility timeout, so Redis never gives a running batch to a second
# worker, and below the 1230 second shutdown grace period, so a worker that drains for a deploy finishes its batch.
@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=15 * 60,
    time_limit=16 * 60,
)
def run_trino_compile_check_task(
    team_id: int,
    run_id: str,
    explain: bool,
    limit: int | None = None,
    saved_query_ids: list[str] | None = None,
    batch_index: int = 0,
    results: dict[str, str | None] | None = None,
) -> None:
    from products.managed_warehouse.backend.trino_compile_check_run import run_trino_compile_check  # noqa: PLC0415

    run_trino_compile_check(
        team_id,
        run_id=run_id,
        explain=explain,
        limit=limit,
        saved_query_ids=saved_query_ids,
        batch_index=batch_index,
        results=results,
    )


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def check_managed_warehouse_budgets() -> None:
    from products.managed_warehouse.backend.logic import budget_alerts  # noqa: PLC0415

    for organization_id in budget_alerts.organization_ids_to_check():
        check_managed_warehouse_budget_for_org.delay(organization_id)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value, soft_time_limit=60, time_limit=90)
def check_managed_warehouse_budget_for_org(organization_id: str) -> None:
    from products.managed_warehouse.backend.logic import budget_alerts  # noqa: PLC0415

    budget_alerts.check_organization_budget(organization_id)
