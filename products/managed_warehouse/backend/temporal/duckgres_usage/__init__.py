from products.managed_warehouse.backend.temporal.duckgres_usage.activities import (
    ack_duckgres_usage,
    poll_duckgres_usage,
)
from products.managed_warehouse.backend.temporal.duckgres_usage.workflow import PollDuckgresUsageWorkflow

WORKFLOWS = [PollDuckgresUsageWorkflow]
ACTIVITIES = [
    poll_duckgres_usage,
    ack_duckgres_usage,
]
