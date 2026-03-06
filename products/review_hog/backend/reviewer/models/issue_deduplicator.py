from pydantic import BaseModel, Field


class DuplicateIssue(BaseModel):
    """Information about a duplicate issue."""

    id: str = Field(description="Issue ID that should be removed")


class IssueDeduplication(BaseModel):
    """Result of deduplication analysis for issues."""

    duplicates: list[DuplicateIssue] = Field(
        description="List of duplicate issues that should be removed, with explanations"
    )
