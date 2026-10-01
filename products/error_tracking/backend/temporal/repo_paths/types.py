import dataclasses
from typing import Final

BUDGET_EXHAUSTED_OUTCOME: Final = "budget_exhausted"


@dataclasses.dataclass(frozen=True)
class RepoPathsWorkflowInputs:
    # Only ids cross the Temporal boundary. The activity reads the release and writes the list itself.
    team_id: int
    release_id: str


@dataclasses.dataclass(frozen=True)
class StoreReleaseFileListInputs:
    team_id: int
    release_id: str
    last_try: bool
