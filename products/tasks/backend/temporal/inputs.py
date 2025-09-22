import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass
class TaskProcessingInputs:
    """Input parameters for task processing workflow."""

    task_id: str
    team_id: int
    user_id: Optional[int] = None

    def __post_init__(self):
        # Validate task_id is a valid UUID
        uuid.UUID(self.task_id)


@dataclass
class CreatePRInputs:
    """Input parameters for creating a pull request."""

    task_processing_inputs: TaskProcessingInputs
    branch_name: str


@dataclass
class CommitChangesInputs:
    """Input parameters for committing changes."""

    task_processing_inputs: TaskProcessingInputs
    branch_name: str
    file_changes: list[dict[str, str]]
