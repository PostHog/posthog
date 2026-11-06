from collections.abc import Callable
from typing import Any

from posthog.temporal.common.base import PostHogWorkflow

from .activities import sync_access_rules_activity
from .workflows import SyncAccessRulesWorkflow

WORKFLOWS: list[type[PostHogWorkflow]] = [SyncAccessRulesWorkflow]
ACTIVITIES: list[Callable[..., Any]] = [sync_access_rules_activity]

__all__ = ["ACTIVITIES", "WORKFLOWS"]
