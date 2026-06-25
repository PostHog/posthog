from pydantic import BaseModel, Field


class DuplicateIssue(BaseModel):
    """A finding flagged as a duplicate, to be removed."""

    id: str = Field(description="Id of the finding to remove")


class IssueDeduplication(BaseModel):
    """Result of deduplication analysis for findings."""

    duplicates: list[DuplicateIssue] = Field(description="Ids of the findings to remove as duplicates")
