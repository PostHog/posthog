from uuid import UUID

import pytest

from products.uptime.backend.facade import api
from products.uptime.backend.facade.contracts import CreateMonitorInput


@pytest.mark.django_db
class TestMonitorAPI:
    def test_create_and_list(self, team):
        dto = api.create(CreateMonitorInput(team_id=team.id, name="example", url="https://example.com"))

        assert isinstance(dto.id, UUID)
        assert dto.name == "example"
        assert dto.url == "https://example.com"

        all_items = api.list_all()
        assert len(all_items) == 1
        assert all_items[0].id == dto.id
