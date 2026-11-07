from typing import Any

from drf_spectacular.utils import extend_schema_field
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers

from ..facade.contracts import AnalyticsSidebarLayout


@extend_schema_field(AnalyticsSidebarLayout)  # type: ignore[arg-type]
class AnalyticsSidebarLayoutField(serializers.Field):
    def to_internal_value(self, data: Any) -> AnalyticsSidebarLayout:
        try:
            return AnalyticsSidebarLayout.model_validate(data)
        except PydanticValidationError as error:
            raise serializers.ValidationError(
                [
                    f"{'.'.join(str(part) for part in issue['loc']) or 'layout'}: {issue['msg']}"
                    for issue in error.errors()
                ]
            )

    def to_representation(self, value: AnalyticsSidebarLayout) -> dict[str, Any]:
        return value.model_dump(mode="json", exclude_none=True)


LAYOUT_HELP_TEXT = (
    "The sections of the Analytics pane, from top to bottom. Each section holds links, buttons, metrics and lists. "
    "Links and buttons open PostHog pages or this project's insights, dashboards and notebooks, never other sites. "
    "A section whose items show nothing, such as an empty pinned list, is hidden."
)


class AnalyticsSidebarRequestSerializer(serializers.Serializer):
    layout = AnalyticsSidebarLayoutField(
        help_text=f"{LAYOUT_HELP_TEXT} The layout replaces the whole sidebar, so send every section to keep."
    )


class AnalyticsSidebarSerializer(serializers.Serializer):
    layout = AnalyticsSidebarLayoutField(help_text=LAYOUT_HELP_TEXT)
    customized = serializers.BooleanField(
        help_text="True when the person saved their own layout. False for the default layout."
    )
