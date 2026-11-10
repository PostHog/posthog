from datetime import timedelta

import time_machine
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

import dagster
from parameterized import parameterized

from posthog.models import Organization, User
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthDeviceGrant, OAuthGrant, OAuthRefreshToken
from posthog.models.organization_provisioning import OrganizationProvisioning

from products.growth.dags.oauth import (
    ClearStaleOAuthApplicationsConfig,
    clear_stale_oauth_applications,
    oauth_clear_stale_oauth_applications_job,
    stale_oauth_applications,
)

NOW = "2026-06-15 02:00:00"


@time_machine.travel(NOW, tick=False)
class TestClearStaleOAuthApplications(TestCase):
    def setUp(self):
        self.user = User.objects.create(email="stale-apps@example.com")
        self._counter = 0

    def _app(self, *, age_days: int = 60, **fields) -> OAuthApplication:
        self._counter += 1
        defaults: dict = {
            "name": f"App {self._counter}",
            "client_id": f"client-{self._counter}",
            "client_secret": "",
            "client_type": OAuthApplication.CLIENT_PUBLIC,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": "https://client.example.com/callback",
            "algorithm": "RS256",
            "is_dcr_client": True,
        }
        app = OAuthApplication.objects.create(**{**defaults, **fields})
        OAuthApplication.objects.filter(pk=app.pk).update(created=timezone.now() - timedelta(days=age_days))
        return app

    def _access_token(self, app: OAuthApplication, *, expires_days_ago: int) -> OAuthAccessToken:
        self._counter += 1
        return OAuthAccessToken.objects.create(
            user=self.user,
            application=app,
            token=f"access-{self._counter}",
            expires=timezone.now() - timedelta(days=expires_days_ago),
            scope="openid",
        )

    def _run(self, dry_run: bool = False):
        result = oauth_clear_stale_oauth_applications_job.execute_in_process(
            run_config={"ops": {"clear_stale_oauth_applications": {"config": {"dry_run": dry_run}}}}
        )
        assert result.success
        return result

    def _remaining(self, *apps: OAuthApplication) -> set:
        return set(OAuthApplication.objects.filter(pk__in=[a.pk for a in apps]).values_list("pk", flat=True))

    def test_self_registered_apps_with_no_valid_token_are_deleted(self):
        dcr = self._app()
        cimd = self._app(is_dcr_client=False, is_cimd_client=True, client_id="https://client.example.com/oauth.json")
        old_token_app = self._app()
        self._access_token(old_token_app, expires_days_ago=45)
        revoked_refresh_app = self._app()
        token = self._access_token(revoked_refresh_app, expires_days_ago=45)
        OAuthRefreshToken.objects.create(
            user=self.user,
            application=revoked_refresh_app,
            token="revoked-refresh",
            access_token=token,
            revoked=timezone.now() - timedelta(days=45),
        )

        self._run()

        assert self._remaining(dcr, cimd, old_token_app, revoked_refresh_app) == set()

    @override_settings(CLEAR_EXPIRED_TOKENS_BATCH_SIZE=1, CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL=0)
    def test_every_stale_app_is_deleted_across_batches_with_kept_apps_between_them(self):
        apps = [self._app() for _ in range(5)]
        kept = apps[1::2]
        for app in kept:
            self._access_token(app, expires_days_ago=-1)

        with patch("products.growth.dags.oauth.stale_oauth_applications", wraps=stale_oauth_applications) as select:
            self._run()

        assert self._remaining(*apps) == {a.pk for a in kept}
        # One call for the count, then one for the batch walk, which pages forward by id.
        assert select.call_count == 2

    def test_apps_with_a_token_valid_inside_the_grace_period_are_kept(self):
        live = self._app()
        self._access_token(live, expires_days_ago=-1)
        recently_expired = self._app()
        self._access_token(recently_expired, expires_days_ago=10)
        # The access token is long gone, but the refresh token can still mint a new one.
        unrevoked_refresh = self._app()
        OAuthRefreshToken.objects.create(user=self.user, application=unrevoked_refresh, token="live-refresh")
        pending_grant = self._app()
        OAuthGrant.objects.create(
            user=self.user,
            application=pending_grant,
            code="pending-code",
            expires=timezone.now() + timedelta(minutes=5),
            redirect_uri="https://client.example.com/callback",
            scope="openid",
            code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            code_challenge_method="S256",
        )
        pending_device = self._app()
        OAuthDeviceGrant.objects.create(
            client_id=pending_device.client_id,
            device_code="pending-device",
            user_code="BCDF-GHJK",
            expires=timezone.now() + timedelta(minutes=5),
        )

        self._run()

        kept = [live, recently_expired, unrevoked_refresh, pending_grant, pending_device]
        assert self._remaining(*kept) == {a.pk for a in kept}

    @parameterized.expand(
        [
            ("recently_registered", {"age_days": 10}),
            ("not_self_registered", {"is_dcr_client": False}),
            ("first_party", {"is_first_party": True}),
            ("verified", {"is_verified": True}),
            ("provisioning_partner", {"is_provisioning_partner": True}),
            ("has_provisioning_config", {"_provisioning_config": {"signing": "required"}}),
        ]
    )
    def test_apps_outside_the_cleanup_scope_are_kept(self, _name, fields):
        app = self._app(**fields)
        self._run()
        assert self._remaining(app) == {app.pk}

    def test_org_linked_and_referenced_apps_are_kept(self):
        organization = Organization.objects.create(name="Partner org")
        org_linked = self._app(organization=organization)
        referenced = self._app()
        OrganizationProvisioning.objects.create(
            organization=Organization.objects.create(name="Provisioned org"),
            partner=OrganizationProvisioning.Partner.PROVISIONING_API,
            application=referenced,
        )

        self._run()

        assert self._remaining(org_linked, referenced) == {org_linked.pk, referenced.pk}

    def test_dry_run_reports_without_deleting(self):
        app = self._app()
        context = dagster.build_op_context()

        clear_stale_oauth_applications(context, ClearStaleOAuthApplicationsConfig(dry_run=True))

        assert self._remaining(app) == {app.pk}
        metadata = context.get_output_metadata("result")
        assert metadata is not None
        assert metadata["stale_applications_found"].value == 1
        assert metadata["stale_applications_deleted"].value == 0
