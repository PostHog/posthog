from typing import Literal

from pydantic import BaseModel, Field

from products.review_hog.backend.reviewer.models.issues_review import IssuePriority


# Pydantic model matching the issue_validation schema
class IssueValidation(BaseModel):
    is_valid: bool = Field(description="Whether the suggested change should be implemented (true) or dismissed (false)")
    argumentation: str = Field(
        description=(
            "Focused, concise explanation covering why the change should be implemented or dismissed."
            " Should include technical reasoning and potential impact."
        )
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
    adjusted_priority: IssuePriority | None = Field(
        default=None,
        description=(
            "Set this only if your investigation shows the reviewer's priority is wrong — raise or lower it to the"
            " correct severity. Leave null to keep the reviewer's priority. Lowering to `consider` keeps the finding"
            " on record but stops it being surfaced."
        ),
    )
