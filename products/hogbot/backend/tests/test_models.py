from django.test import TestCase

from posthog.models import Organization, Team

from products.hogbot.backend.models import HogbotRuntime


class TestHogbotModels(TestCase):
    databases = {"default", "hogbot_db_writer"}

    def test_runtime_defaults(self):
        organization = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=organization, name="Test Team")
        instance = HogbotRuntime.objects.create(team_id=team.pk)

        self.assertIsNone(instance.latest_snapshot_external_id)
