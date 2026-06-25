from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from posthog.models import OAuthApplication
from posthog.models.oauth import OAuthApplicationAuthBrand
from posthog.temporal.oauth import POSTHOG_AI_APP_CLIENT_ID_DEV


class TestSetupTasksOAuth(TestCase):
    @override_settings(DEBUG=True)
    def test_creates_posthog_ai_dev_oauth_app(self) -> None:
        call_command("setup_tasks_oauth", stdout=StringIO())

        app = OAuthApplication.objects.get(client_id=POSTHOG_AI_APP_CLIENT_ID_DEV)
        assert app.name == "PostHog AI Dev App"
        assert app.client_type == OAuthApplication.CLIENT_CONFIDENTIAL
        assert app.authorization_grant_type == OAuthApplication.GRANT_AUTHORIZATION_CODE
        assert app.redirect_uris == "http://localhost:8000/authorize"
        assert app.auth_brand == OAuthApplicationAuthBrand.POSTHOG.value
        assert app.is_verified is True
        assert app.is_first_party is True
