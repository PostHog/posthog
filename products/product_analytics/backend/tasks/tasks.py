from celery import shared_task

from posthog.tasks.utils import CeleryQueue

from products.product_analytics.backend import logic


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    soft_time_limit=600,
    time_limit=660,
    name="products.product_analytics.backend.tasks.expire_agent_insight_reads",
)
def expire_agent_insight_reads() -> None:
    logic.expire_agent_insight_reads()
