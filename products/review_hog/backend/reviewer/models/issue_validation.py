from typing import Literal

from pydantic import BaseModel, Field

from products.review_hog.backend.reviewer.models.issues_review import IssuePriority


# Pydantic model matching the issue_validation schema
class IssueValidation(BaseModel):
    is_valid: bool = Field(description="Whether the suggested change should be implemented (true) or dismissed (false)")
    argumentation: str = Field(
        description=(
            "Your verification delta as labeled markdown bullets, never a restatement of the issue"
            " description (every reader sees that right next to your verdict). Bullets: '- **Checked:**'"
            " what you investigated (files, call sites, types, guards); '- **Found:**' the decisive"
            " evidence, with file:line anchors; '- **Impact:**' the confirmed consequence (for a"
            " dismissal, why it does not meet the bar); '- **Priority:**' only when setting"
            " adjusted_priority, the reason. Repeat a label for several distinct points. Keep every fact"
            " needed to justify the verdict; cut only restatement."
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
