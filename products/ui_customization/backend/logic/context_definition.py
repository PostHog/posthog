from posthog.dataclasses import frozen

from ..facade.contracts import CustomizationLayout
from ..facade.enums import CustomizationContext


@frozen
class CustomizationContextDefinition:
    context: CustomizationContext
    layout_schema: type[CustomizationLayout]
    defaults: CustomizationLayout
