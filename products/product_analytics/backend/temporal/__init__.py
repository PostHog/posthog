from typing import TYPE_CHECKING

from .upgrade_queries_activities import get_insights_to_migrate, migrate_insights_batch
from .upgrade_queries_workflow import UpgradeQueriesWorkflow

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [
    UpgradeQueriesWorkflow,
]
ACTIVITIES: list[ActivityDefinition] = [
    get_insights_to_migrate,
    migrate_insights_batch,
]
