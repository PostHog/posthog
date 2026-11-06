"""Saves a translated Resend automation as a draft workflow."""

from collections.abc import Mapping
from typing import Any

from products.workflows.backend.facade.contracts import ImportedEmail, ProviderAutomationResult
from products.workflows.backend.facade.enums import WorkflowImportSource
from products.workflows.backend.services.resend_import.translator import translate_automation


def import_resend_automation(
    team_id: int, user_id: int | None, automation: dict[str, Any], emails: Mapping[str, ImportedEmail | None]
) -> ProviderAutomationResult:
    """Saves a Resend automation as a draft workflow. An automation imported before stays as it is."""
    # The draft check lives in the views layer, and importing it at load time would bring the whole API with it.
    from products.workflows.backend.presentation.views.workflow_import_drafts import (  # noqa: PLC0415
        save_provider_draft,
    )

    return save_provider_draft(team_id, user_id, translate_automation(automation, emails), WorkflowImportSource.RESEND)
