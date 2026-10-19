from celery import shared_task

from products.notebooks.backend.warehouse_tables import finish_warehouse_table_save


@shared_task(ignore_result=True, soft_time_limit=300, time_limit=330)
def save_notebook_warehouse_table(team_id: int, run_id: str) -> None:
    finish_warehouse_table_save(team_id, run_id)
