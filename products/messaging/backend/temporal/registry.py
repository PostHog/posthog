"""Workflow and activity registration lists for the provider import worker.

Core reaches these through ``facade/temporal.py``.
"""

from collections.abc import Callable

from products.messaging.backend.temporal.activities import (
    fail_contacts_cohort_activity,
    fill_contacts_cohort_activity,
    finish_provider_import_run_activity,
    import_contact_chunk_activity,
    record_people_import_activity,
    run_provider_import_step_activity,
)
from products.messaging.backend.temporal.workflow import ProviderContactsImportWorkflow, ProviderImportWorkflow

WORKFLOWS = [ProviderImportWorkflow, ProviderContactsImportWorkflow]

ACTIVITIES: list[Callable[..., object]] = [
    run_provider_import_step_activity,
    finish_provider_import_run_activity,
    import_contact_chunk_activity,
    fill_contacts_cohort_activity,
    fail_contacts_cohort_activity,
    record_people_import_activity,
]

__all__ = ["WORKFLOWS", "ACTIVITIES"]
