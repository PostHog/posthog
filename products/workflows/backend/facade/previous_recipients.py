"""People a cross-product entry point already emailed about the same record, so a new send can skip them."""

from products.workflows.backend.facade.contracts import PreviousRecipients, TooManyPreviousRecipients
from products.workflows.backend.services.previous_recipients import (
    MAX_PREVIOUS_RECIPIENTS,
    build_previous_recipients_cohort,
)

__all__ = [
    "MAX_PREVIOUS_RECIPIENTS",
    "PreviousRecipients",
    "TooManyPreviousRecipients",
    "build_previous_recipients_cohort",
]
