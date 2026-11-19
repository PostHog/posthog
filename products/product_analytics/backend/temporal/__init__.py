from collections.abc import Callable

from .upgrade_queries_activities import get_insights_to_migrate, migrate_insights_batch
from .upgrade_queries_workflow import UpgradeQueriesWorkflow

WORKFLOWS = [
    UpgradeQueriesWorkflow,
]
ACTIVITIES: list[Callable[..., object]] = [
    get_insights_to_migrate,
    migrate_insights_batch,
]
