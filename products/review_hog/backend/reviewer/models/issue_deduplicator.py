from pydantic import BaseModel, Field


class DuplicateIssue(BaseModel):
    """A finding flagged as a duplicate, to be removed."""

    id: str = Field(description="Id of the finding to remove")


class IssueDeduplication(BaseModel):
    """Result of deduplication analysis for findings."""

    duplicates: list[DuplicateIssue] = Field(description="Ids of the findings to remove as duplicates")


class FlashDuplicateIssue(BaseModel):
    """A finding flagged as a duplicate, with what it repeats."""

    id: str = Field(description="Id of the finding to remove")
    duplicate_of: str = Field(
        description=(
            "Id of what already raises the same problem: the finding kept in its place, a prior finding, or a"
            " prior comment"
        )
    )


class FlashIssueDeduplication(BaseModel):
    """Result of a Flash deduplication: every duplicate names what it repeats."""

    duplicates: list[FlashDuplicateIssue] = Field(description="The findings to remove as duplicates")
