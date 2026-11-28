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
