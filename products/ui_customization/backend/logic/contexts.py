from ..facade.contracts import CustomizationDescription, CustomizationLayout
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


def describe_context(context: str) -> CustomizationDescription:
    definition = resolve_context(context)
    return CustomizationDescription(
        context=definition.context,
        layout_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **definition.layout_schema.model_json_schema(mode="validation"),
        },
        default_layout=definition.defaults,
    )
