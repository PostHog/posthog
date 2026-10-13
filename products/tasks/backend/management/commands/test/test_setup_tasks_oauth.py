from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from parameterized import parameterized

from posthog.models import OAuthApplication
from posthog.models.oauth import OAuthApplicationAuthBrand
from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    ARRAY_APP_ID_DEV,
    POSTHOG_AI_APP_CLIENT_ID_DEV,
    POSTHOG_AI_APP_ID_DEV,
    SIGNALS_APP_CLIENT_ID_DEV,
    SIGNALS_APP_ID_DEV,
)

DEV_CLIENT_IDS = [ARRAY_APP_CLIENT_ID_DEV, POSTHOG_AI_APP_CLIENT_ID_DEV, SIGNALS_APP_CLIENT_ID_DEV]


@override_settings(DEBUG=False, CLOUD_DEPLOYMENT="DEV")
class TestSetupTasksOAuth(TestCase):
    @parameterized.expand(
        [
            (
                "array",
                ARRAY_APP_CLIENT_ID_DEV,
                ARRAY_APP_ID_DEV,
                {
                    "name": "Array Dev App",
                    "client_type": OAuthApplication.CLIENT_PUBLIC,
                    "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                    "redirect_uris": "http://localhost:8237/callback http://localhost:8239/callback",
                },
            ),
            (
                "posthog_ai",
                POSTHOG_AI_APP_CLIENT_ID_DEV,
                POSTHOG_AI_APP_ID_DEV,
                {
                    "name": "PostHog AI Dev App",
                    "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
                    "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                    "redirect_uris": "http://localhost:8000/authorize",
                    "auth_brand": OAuthApplicationAuthBrand.POSTHOG.value,
                    "is_verified": True,
                    "is_first_party": True,
                },
            ),
            (
                "signals",
                SIGNALS_APP_CLIENT_ID_DEV,
                SIGNALS_APP_ID_DEV,
                {
                    "name": "Signals Dev App",
                    "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
                    "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                    "redirect_uris": "http://localhost:8000/authorize",
                    "auth_brand": OAuthApplicationAuthBrand.POSTHOG.value,
                    "is_verified": True,
                    "is_first_party": True,
                },
            ),
        ]
    )
    def test_creates_dev_oauth_app_and_reruns_cleanly(
        self, _name: str, client_id: str, expected_id: str, expected: dict
    ) -> None:
        call_command("setup_tasks_oauth", stdout=StringIO())
        call_command("setup_tasks_oauth", stdout=StringIO())

        apps = OAuthApplication.objects.filter(client_id=client_id)
        assert apps.count() == 1
        app = apps.get()
        assert str(app.id) == expected_id
        for field, value in expected.items():
            assert getattr(app, field) == value, field

    @parameterized.expand(
        [
            ("us", "US", False),
            ("eu", "EU", False),
            ("hosted_dev", "DEV", True),
            ("unset_region", None, True),
        ]
    )
    def test_creates_apps_outside_production_regions_only(
        self, _name: str, region: str | None, should_create: bool
    ) -> None:
        with override_settings(CLOUD_DEPLOYMENT=region):
            call_command("setup_tasks_oauth", stdout=StringIO())

        created = OAuthApplication.objects.filter(client_id__in=DEV_CLIENT_IDS).count()
        assert created == (len(DEV_CLIENT_IDS) if should_create else 0)

    def test_warns_when_an_existing_app_has_the_wrong_id(self) -> None:
        OAuthApplication.objects.create(
            client_id=POSTHOG_AI_APP_CLIENT_ID_DEV,
            name="PostHog AI Dev App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8000/authorize",
            algorithm="RS256",
        )

        out = StringIO()
        call_command("setup_tasks_oauth", stdout=out)

        assert f"expected {POSTHOG_AI_APP_ID_DEV}" in out.getvalue()
