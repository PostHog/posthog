from dataclasses import dataclass
from typing import Optional
import uuid


@dataclass
class IssueProcessingInputs:
    """Input parameters for issue processing workflow."""

    issue_id: str
    team_id: int
    previous_status: str
    new_status: str
    user_id: Optional[int] = None

    def __post_init__(self):
        # Validate issue_id is a valid UUID
        uuid.UUID(self.issue_id)
