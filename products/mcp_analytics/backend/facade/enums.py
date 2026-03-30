from enum import StrEnum


class SubmissionKind(StrEnum):
    FEEDBACK = "feedback"
    MISSING_CAPABILITY = "missing_capability"


class FeedbackCategory(StrEnum):
    RESULTS = "results"
    USABILITY = "usability"
    BUG = "bug"
    DOCS = "docs"
    OTHER = "other"
