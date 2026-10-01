from posthog.enums import LabeledStrEnum


# Each label repeats its value, because the API documents these choices as plain values.
class UserInterviewSearchDocumentType(LabeledStrEnum):
    TRANSCRIPT = "transcript", "transcript"
    SUMMARY = "summary", "summary"
