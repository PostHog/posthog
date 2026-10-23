from enum import StrEnum

from posthog.dataclasses import frozen


class NoteLevel(StrEnum):
    # The step behaves differently in PostHog, and the note says how.
    APPROXIMATED = "approximated"
    # The setting has no PostHog equivalent and was left out.
    UNSUPPORTED = "unsupported"
    # The step is imported but needs a setting only the team can give, like an email sender.
    NEEDS_INPUT = "needs_input"


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
