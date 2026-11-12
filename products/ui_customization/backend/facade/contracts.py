from pydantic import JsonValue

from posthog.dataclasses import frozen

from .analytics import AnalyticsFragmentLayout
from .enums import CustomizationContext

CustomizationLayout = AnalyticsFragmentLayout


@frozen
class Customization:
    layout: CustomizationLayout
    customized: bool


@frozen
class CustomizationDescription:
    context: CustomizationContext
    layout_schema: dict[str, JsonValue]
    default_layout: CustomizationLayout


class UnavailableTargets(Exception):
    """The layout points at insights, dashboards or notebooks this person cannot open in this project."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems
