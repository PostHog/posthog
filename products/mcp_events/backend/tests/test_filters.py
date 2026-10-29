from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import PermissionDenied

from posthog.hogql.property_access_types import RestrictedProperty

from posthog.models import PropertyDefinition, Team, User

from products.mcp_events.backend.logic.filters import MCPEventFilterAccessValidator, canonicalize_event_filters
from products.mcp_events.backend.logic.properties import MCPEventPropertyAccess


class TestMCPEventFilterAccess(SimpleTestCase):
    @parameterized.expand(["$feature/secret", "$feature_flags", "$feature_flags.secret", "$active_feature_flags"])
    def test_restricted_flag_map_denies_all_aliases(self, alias: str) -> None:
        with self.assertRaises(PermissionDenied):
            MCPEventPropertyAccess.validate(alias, {"$feature_flags"})
        MCPEventPropertyAccess.validate("plan", {"$feature_flags"})

    @parameterized.expand(
        [
            ("event", PropertyDefinition.Type.EVENT, None),
            ("person", PropertyDefinition.Type.PERSON, None),
            ("group:0", PropertyDefinition.Type.GROUP, 0),
        ]
    )
    def test_snapshot_accepts_unrelated_properties_and_rejects_restricted_reads(
        self, scope: str, property_type: int, group_type_index: int | None
    ) -> None:
        team = Team(pk=1, project_id=1)
        user = User(pk=1)
        with (
            patch(
                "products.mcp_events.backend.logic.filters.get_restricted_properties_with_group_type_index_for_team",
                return_value={
                    RestrictedProperty(name="secret", property_type=property_type, group_type_index=group_type_index)
                },
            ),
            patch("posthog.models.event.new_events_schema.use_new_events_schema", return_value=False),
        ):
            MCPEventFilterAccessValidator.validate_snapshot({scope: ["public"]}, team=team, user=user)
            for name in ("secret", None):
                with self.assertRaises(PermissionDenied):
                    MCPEventFilterAccessValidator.validate_snapshot({scope: [name]}, team=team, user=user)

    @parameterized.expand(
        [
            ("numeric_id", {"actions": [{"id": 12, "type": "actions"}]}),
            ("string_id", {"actions": [{"id": "12", "type": "actions"}]}),
            ("action_in_events", {"events": [{"id": "12", "type": "actions"}]}),
        ]
    )
    def test_equivalent_action_filters_share_one_identity(self, _name: str, filters: dict) -> None:
        self.assertEqual(
            canonicalize_event_filters(filters).get("actions"),
            [{"id": "12", "type": "actions"}],
        )
