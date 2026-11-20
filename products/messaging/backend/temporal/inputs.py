from posthog.dataclasses import frozen

from products.messaging.backend.provider_imports.base import PeopleImportPlan


@frozen
class ProviderImportWorkflowInputs:
    team_id: int
    run_id: str
    steps: list[str]


@frozen
class ProviderImportStepInputs:
    team_id: int
    run_id: str
    step: str


@frozen
class ProviderImportRunInputs:
    team_id: int
    run_id: str


@frozen
class ProviderImportStepResult:
    people_imports: list[PeopleImportPlan]


@frozen
class ProviderContactsImportInputs:
    team_id: int
    run_id: str
    people_imports: list[PeopleImportPlan]


@frozen
class ContactChunkInputs:
    team_id: int
    storage_prefix: str
    chunk: int
    send_events: bool
    created_by_id: int | None = None


@frozen
class ContactChunkResult:
    people: int
    found: int
    # The activity attempt that finished the part, so the run can count retried parts.
    attempt: int


@frozen
class ContactsCohortInputs:
    team_id: int
    cohort_id: int
    storage_prefix: str
    chunks: int
    created_by_id: int | None = None


@frozen
class ContactsImportOutcome:
    people: int = 0
    found: int = 0
    removed: int = 0
    failed_lists: int = 0
    retried_chunks: int = 0


@frozen
class RecordPeopleImportInputs:
    team_id: int
    run_id: str
    step: str
    outcome: ContactsImportOutcome
