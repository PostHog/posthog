from ..facade.contracts import CustomizationLayout
from .analytics_sidebar import ANALYTICS_SIDEBAR
from .context_definition import CustomizationContextDefinition

CONTEXTS: dict[str, CustomizationContextDefinition] = {ANALYTICS_SIDEBAR.context: ANALYTICS_SIDEBAR}


def resolve_context(context: str) -> CustomizationContextDefinition:
    try:
        return CONTEXTS[context]
    except KeyError:
        raise ValueError("Unsupported customization context") from None


def validate_layout(*, context: str, layout: object) -> CustomizationLayout:
    return resolve_context(context).layout_schema.model_validate(layout)
