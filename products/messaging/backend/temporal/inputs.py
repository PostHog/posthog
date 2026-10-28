from posthog.dataclasses import frozen


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
