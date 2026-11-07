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
