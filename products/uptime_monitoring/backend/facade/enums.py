"""Choice vocabularies the models store and the API renders.

They live here rather than on the models because a product's facade must not import Django, and
both halves need the same list.
"""

from posthog.enums import LabeledStrEnum


class UptimeMonitorMethod(LabeledStrEnum):
    GET = "GET", "GET"
    HEAD = "HEAD", "HEAD"
