import pytest
from posthog.test.base import BaseTest

from products.enterprise.backend.models.event_definition import EnterpriseEventDefinition


class TestEventDefinition(BaseTest):
    def test_errors_on_invalid_verified_by_type(self):
        with pytest.raises(ValueError):
            EnterpriseEventDefinition.objects.create(
                team=self.team,
                name="enterprise event",
                owner=self.user,
                verified_by="Not user id",  # type: ignore
            )

    def test_default_verified_false(self):
        eventDef = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event", owner=self.user)
        assert eventDef.verified is False
