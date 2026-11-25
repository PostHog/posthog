"""Shared helpers for feature flag write tests. This module is not a test module itself."""

from typing import TYPE_CHECKING

from rest_framework.test import APIClient

from posthog.constants import AvailableFeature

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.facade.testing import create_property_access_control
from products.event_definitions.backend.models import PropertyDefinition

if TYPE_CHECKING:
    from posthog.test.base import APIBaseTest

    from rest_framework.response import _MonkeyPatchedResponse

# Each mode turns a flag on without sending new targeting. The serializer must then check the stored filters.
# "restore" expects a soft-deleted flag stored with active=True. The other modes expect a disabled flag.
TURN_ON_MODES = ("patch", "empty", "action", "restore")


def turn_flag_on(client: APIClient, flag_url: str, mode: str) -> "_MonkeyPatchedResponse":
    if mode == "action":
        return client.post(f"{flag_url}enable/", {}, format="json")
    if mode == "restore":
        return client.patch(flag_url, {"deleted": False}, format="json")
    if mode == "empty":
        return client.patch(flag_url, {"active": True, "filters": {}}, format="json")
    return client.patch(flag_url, {"active": True}, format="json")


def restrict_properties(
    test: "APIBaseTest",
    restrictions: list[tuple[str, int, int | None]],
    *,
    member: PropertyAccessLevel | None = None,
) -> None:
    test.organization.available_product_features = [
        {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
    ]
    test.organization.save()
    for name, property_type, group_type_index in restrictions:
        definition = PropertyDefinition.objects.create(
            team=test.team, name=name, property_type="String", type=property_type, group_type_index=group_type_index
        )
        create_property_access_control(
            team_id=test.team.pk, property_definition_id=definition.id, access_level=PropertyAccessLevel.NONE.value
        )
        if member is not None:
            create_property_access_control(
                team_id=test.team.pk,
                property_definition_id=definition.id,
                access_level=member.value,
                organization_member_id=test.organization_membership.id,
            )


SALARY = ("salary", PropertyDefinition.Type.PERSON, None)
SALARY_CONDITION = {"key": "salary", "type": "person", "value": "100000", "operator": "gt"}
