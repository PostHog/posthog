from uuid import UUID

APPLY_LENS_WORKFLOW_NAME = "replay-vision-apply-lens"

# Capped so `replay-vision-apply-lens-{lens_uuid:36}-{session_id}` fits the 255-char `ReplayObservation.workflow_id` column.
MAX_SESSION_ID_LENGTH = 128


def build_apply_lens_workflow_id(lens_id: UUID, session_id: str) -> str:
    """Deterministic Temporal workflow id for one (lens, session) application."""
    return f"{APPLY_LENS_WORKFLOW_NAME}-{lens_id}-{session_id}"
