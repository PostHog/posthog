from pydantic import BaseModel, Field

from products.review_hog.backend.reviewer.models.issues_review import Issue
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk


class ValidationMarkdownReportIssue(BaseModel):
    issue: Issue = Field(description="The issue that was validated")


class ValidationMarkdownReportChunk(BaseModel):
    chunk: Chunk = Field(description="The chunk containing the issue")
    validated_issues: list[ValidationMarkdownReportIssue] = Field(description="The issues that were validated")


class ValidationMarkdownReport(BaseModel):
    chunks: list[ValidationMarkdownReportChunk] = Field(description="The chunks that were validated")
