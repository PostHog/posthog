"""Choice vocabularies the models store and the API renders.

They live here rather than on the models because a product's facade must not import Django, and
both halves need the same list.
"""

from posthog.enums import LabeledStrEnum


class JourneyStepType(LabeledStrEnum):
    PAGEVIEW = "pageview", "Pageview"
    ELEMENT_CLICK = "element_click", "Element click"


class UrlMatching(LabeledStrEnum):
    EXACT = "exact", "Exact"
    CONTAINS = "contains", "Contains"
    REGEX = "regex", "Regex"


class JourneySource(LabeledStrEnum):
    TOOLBAR = "toolbar", "Toolbar"
    MANUAL = "manual", "Manual"


class JourneyRunTrigger(LabeledStrEnum):
    MANUAL = "manual", "Manual"
    DEPLOY = "deploy", "Deploy"


class JourneyRunStatus(LabeledStrEnum):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    PASSED = "passed", "Passed"
    FAILED = "failed", "Failed"
    ERRORED = "errored", "Errored"


class JourneyRunStepStatus(LabeledStrEnum):
    PASSED = "passed", "Passed"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class JourneyStepFailureReason(LabeledStrEnum):
    ELEMENT_NOT_FOUND = "element_not_found", "Element not found"
    ELEMENT_NOT_VISIBLE = "element_not_visible", "Element not visible"
    ELEMENT_OBSCURED = "element_obscured", "Element covered by another element"
    ELEMENT_OUTSIDE_VIEWPORT_UNREACHABLE = (
        "element_outside_viewport_unreachable",
        "Element outside the viewport and can't be scrolled to",
    )
    NAVIGATION_MISMATCH = "navigation_mismatch", "Page URL doesn't match"
    NAVIGATION_FAILED = "navigation_failed", "Page failed to load"
    NAVIGATION_BLOCKED = "navigation_blocked", "Navigation to a URL that isn't allowed"
    TIMEOUT = "timeout", "Timed out"


class JourneyVisualChange(LabeledStrEnum):
    UNCHANGED = "unchanged", "Unchanged"
    CHANGED = "changed", "Changed"
    NEW = "new", "New"


class JourneyDeployStatus(LabeledStrEnum):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    PASSED = "passed", "Passed"
    FAILED = "failed", "Failed"
    ERRORED = "errored", "Errored"
    NO_RUNS = "no_runs", "No runs"


class JourneyDeploySkipReason(LabeledStrEnum):
    JOURNEY_NOT_FOUND = "journey_not_found", "Journey not found"
    NOT_RUNNABLE = "not_runnable", "Journey can't run"
    TARGET_NOT_ALLOWED = "target_not_allowed", "Start page isn't allowed"
    RUN_IN_PROGRESS = "run_in_progress", "Run already in progress"
