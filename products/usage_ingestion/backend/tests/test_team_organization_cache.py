from uuid import uuid4

from unittest.mock import patch

from django.test import override_settings

from posthog.models.team.team import Team

from products.usage_ingestion.backend import team_organization_cache
from products.usage_ingestion.backend.tasks.receivers import publish_team_organization_on_save


def test_team_organization_mapping_contains_only_ownership_fields() -> None:
    team = Team(id=123, organization_id=uuid4())

    mapping = team_organization_cache._load_team_organization(team)

    assert mapping == {"team_id": team.id, "organization_id": str(team.organization_id)}


@override_settings(USAGE_INGESTION_REDIS_URL="redis://usage-ingestion")
def test_team_save_enqueues_mapping_after_commit() -> None:
    team = Team(id=123, organization_id=uuid4())

    with (
        patch("products.usage_ingestion.backend.tasks.receivers.transaction.on_commit") as on_commit,
        patch("products.usage_ingestion.backend.tasks.tasks.update_team_organization_cache_task.delay") as delay,
    ):
        publish_team_organization_on_save(Team, team)
        on_commit.assert_called_once()
        on_commit.call_args.args[0]()

    delay.assert_called_once_with(team.id)
