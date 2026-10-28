"""DRF fields that reference an integration row. The facade cannot hold DRF code, so they live here."""

from collections.abc import Iterable
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.integrations.backend.facade.api import IntegrationManager, IntegrationRecord
from products.integrations.backend.facade.contracts import IntegrationNotFound


@extend_schema_field(OpenApiTypes.INT)
class IntegrationReferenceField(serializers.Field):
    """An integration id of the request's team. Use it instead of a `PrimaryKeyRelatedField` on `Integration`.

    It reads the team from the serializer context (`team_id`, or `get_team`), so a row of another team
    is "does not exist". Pass `kinds` to accept only rows of these kinds.
    """

    default_error_messages = {
        "does_not_exist": 'Invalid pk "{pk_value}" - object does not exist.',
        "incorrect_type": "Incorrect type. Expected pk value, received {data_type}.",
        "no_team": "The serializer context has no team.",
    }

    def __init__(self, *, kinds: Iterable[str] = (), **kwargs: Any) -> None:
        self.kinds = frozenset(kinds)
        super().__init__(**kwargs)

    def _team_id(self) -> int:
        team_id = self.context.get("team_id")
        if team_id is None and "get_team" in self.context:
            team_id = self.context["get_team"]().id
        if team_id is None:
            self.fail("no_team")
        return int(team_id)

    def to_internal_value(self, data: object) -> IntegrationRecord:
        if isinstance(data, bool) or not isinstance(data, int | str):
            self.fail("incorrect_type", data_type=type(data).__name__)
        try:
            integration_id = int(data)
        except ValueError:
            self.fail("incorrect_type", data_type=type(data).__name__)
        try:
            record = IntegrationManager.any.get(self._team_id(), integration_id)
        except IntegrationNotFound:
            self.fail("does_not_exist", pk_value=data)
        if self.kinds and record.kind not in self.kinds:
            self.fail("does_not_exist", pk_value=data)
        return record

    def to_representation(self, value: IntegrationRecord | int) -> int:
        return value if isinstance(value, int) else value.id
