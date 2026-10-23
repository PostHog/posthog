from posthog.dataclasses import frozen

from products.workflows.backend.facade.enums import WorkflowImportNoteLevel as NoteLevel


@frozen
class ImportNote:
    level: NoteLevel
    message: str
    # The PostHog step the note is about, or None for the whole workflow.
    step_id: str | None = None
    step_name: str | None = None


@frozen
class TranslatedWorkflow:
    source_id: str
    name: str
    workflow: dict
    notes: tuple[ImportNote, ...]
