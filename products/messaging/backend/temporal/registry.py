"""Workflow and activity registration lists for the provider import worker.

Core reaches these through ``facade/temporal.py``.
"""

from typing import TYPE_CHECKING

from products.messaging.backend.temporal.activities import (
    finish_provider_import_run_activity,
    run_provider_import_step_activity,
)
from products.messaging.backend.temporal.workflow import ProviderImportWorkflow

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [ProviderImportWorkflow]

ACTIVITIES: list[ActivityDefinition] = [run_provider_import_step_activity, finish_provider_import_run_activity]

__all__ = ["WORKFLOWS", "ACTIVITIES"]
