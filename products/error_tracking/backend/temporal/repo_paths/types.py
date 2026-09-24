import dataclasses


@dataclasses.dataclass(frozen=True)
class RepoPathsWorkflowInputs:
    # Only ids cross the Temporal boundary. The activity reads the release and writes the list itself.
    team_id: int
    release_id: str
