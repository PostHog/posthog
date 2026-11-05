"""Switching the workflows suggestions scout on and off as workflows opt in and out."""

from products.workflows.backend.models.hog_flow.hog_flow import AGENT_STEP_TEMPLATE_IDS
from products.workflows.backend.services.suggestions_scout import (
    PROPOSAL_WRITE_SCOPE,
    suggestions_sample,
    suggestions_scout_refusal,
    suggestions_scout_status,
    sync_suggestions_scout,
)

__all__ = [
    "AGENT_STEP_TEMPLATE_IDS",
    "PROPOSAL_WRITE_SCOPE",
    "suggestions_sample",
    "suggestions_scout_refusal",
    "suggestions_scout_status",
    "sync_suggestions_scout",
]
