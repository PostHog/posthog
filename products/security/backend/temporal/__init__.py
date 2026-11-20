from typing import TYPE_CHECKING

from posthog.temporal.common.base import PostHogWorkflow

from .activities import sync_access_rules_activity
from .workflows import SyncAccessRulesWorkflow

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS: list[type[PostHogWorkflow]] = [SyncAccessRulesWorkflow]
ACTIVITIES: list[ActivityDefinition] = [sync_access_rules_activity]

__all__ = ["ACTIVITIES", "WORKFLOWS"]
