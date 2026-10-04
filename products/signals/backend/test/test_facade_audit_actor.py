from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.facade.api import resolve_audit_actor_for_team


class TestResolveAuditActorForTeam(SimpleTestCase):
    @parameterized.expand(
        [
            ("eligible_user", 42),
            ("no_eligible_member", None),
        ]
    )
    def test_returns_the_temporal_actor_resolution(self, _name: str, resolved_user_id: int | None) -> None:
        with patch(
            "products.signals.backend.temporal.agentic.resolve_acting_user_id_for_team",
            return_value=resolved_user_id,
        ) as resolve_actor:
            assert resolve_audit_actor_for_team(123) == resolved_user_id

        resolve_actor.assert_called_once_with(123)
