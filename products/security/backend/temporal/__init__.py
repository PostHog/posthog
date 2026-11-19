from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.registration import ActivityDefinition

from .activities import sync_access_rules_activity
from .workflows import SyncAccessRulesWorkflow

WORKFLOWS: list[type[PostHogWorkflow]] = [SyncAccessRulesWorkflow]
ACTIVITIES: list[ActivityDefinition] = [sync_access_rules_activity]

__all__ = ["ACTIVITIES", "WORKFLOWS"]
