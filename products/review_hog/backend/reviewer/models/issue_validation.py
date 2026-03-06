from typing import Literal

from pydantic import BaseModel, Field


# Pydantic model matching the issue_validation schema
class IssueValidation(BaseModel):
    is_valid: bool = Field(description="Whether the suggested change should be implemented (true) or dismissed (false)")
    argumentation: str = Field(
        description="Focused, concise explanation covering why the change should be implemented or dismissed. Should include technical reasoning and potential impact."
    )
    category: (
        Literal[
            "bug",
            "security",
            "performance",
            "code_quality",
            "best_practice",
            "documentation",
            "testing",
            "accessibility",
            "compatibility",
        ]
        | None
    ) = Field(None, description="Category of the issue")

    model_config = {"populate_by_name": True}
