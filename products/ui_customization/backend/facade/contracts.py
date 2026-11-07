from posthog.dataclasses import frozen

from .analytics import AnalyticsFragmentLayout

CustomizationLayout = AnalyticsFragmentLayout


@frozen
class Customization:
    layout: CustomizationLayout
    customized: bool
