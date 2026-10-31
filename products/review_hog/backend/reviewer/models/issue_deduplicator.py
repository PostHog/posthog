from pydantic import BaseModel, Field


class DuplicateIssue(BaseModel):
    """A finding flagged as a duplicate, with what it repeats."""

    id: str = Field(description="Id of the finding to remove")
    duplicate_of: str = Field(
        description=(
            "Id of what already raises the same problem: the finding kept in its place, a prior finding, or a"
            " prior comment"
        )
    )


class IssueDeduplication(BaseModel):
    """Result of a deduplication: every duplicate names what it repeats."""

    duplicates: list[DuplicateIssue] = Field(description="The findings to remove as duplicates")
