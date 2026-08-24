from uuid import UUID

from celery import shared_task

from posthog.tasks.utils import CeleryQueue


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=300,
    time_limit=330,
)
def process_genui_generation(team_id: int, genui_id: str, user_id: int, generation_hash: str) -> None:
    from products.notebooks.backend.genui_generation import (  # noqa: PLC0415 — keeps the Canvas builder off Celery task discovery
        materialize_genui_generation,
    )

    materialize_genui_generation(
        team_id=team_id,
        genui_id=UUID(genui_id),
        user_id=user_id,
        generation_hash=generation_hash,
    )
