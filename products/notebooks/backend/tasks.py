from celery import shared_task


@shared_task(ignore_result=True)
def mark_stale_notebook_node_runs_failed() -> None:
    from products.notebooks.backend.sql_v2_reaper import mark_stale_node_runs_failed  # noqa: PLC0415

    mark_stale_node_runs_failed()
