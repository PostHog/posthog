from uuid import UUID

import pytest

from products.uptime.backend.facade import api
from products.uptime.backend.facade.contracts import BulkCreateMonitorInput, BulkCreateMonitorItem, CreateMonitorInput
from products.uptime.backend.models import Monitor


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

    def test_bulk_create_returns_dtos(self, team):
        result = api.bulk_create(
            BulkCreateMonitorInput(
                team_id=team.id,
                items=[
                    BulkCreateMonitorItem(name="PostHog", url="https://posthog.com"),
                    BulkCreateMonitorItem(name="GitHub", url="https://github.com"),
                ],
            )
        )

        assert len(result) == 2
        assert {r.url for r in result} == {"https://posthog.com", "https://github.com"}
        assert Monitor.objects.filter(team_id=team.id).count() == 2
