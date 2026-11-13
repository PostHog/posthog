from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from unittest.mock import patch

from django.db import DEFAULT_DB_ALIAS, OperationalError, connections
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.integration import EMAIL_FROM_CODE_FLAG
from posthog.constants import AvailableFeature
from posthog.models.integration import Integration
from posthog.models.integration.email import lock_sender_domain
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.proxy_record import ProxyRecord
from posthog.models.team import Team
from posthog.models.utils import hash_key_value

from products.workflows.backend.test.email_domain_api_test_case import DOMAIN, ROOT_DOMAIN, EmailDomainApiTestCase
from products.workflows.backend.tests.fakes.world import domain_connect_signing_key_pem

SENDER = f"hello@{DOMAIN}"
TOKEN_AUTHENTICATIONS = ["pak", "oauth"]
ALL_AUTHENTICATIONS = [*TOKEN_AUTHENTICATIONS, "session"]
NO_TOKEN_ACCESS = "This action does not support personal API key access"
MISSING_WRITE_SCOPE = "API key missing required scope 'integration:write'"
REDIRECT_OUTSIDE_POSTHOG = "redirect_uri must point back to PostHog."
SHARED_MAIL_FROM = "Other projects send from this domain, so change its MAIL FROM subdomain in PostHog."


def email_from_code(enabled: bool | None) -> Any:
    return patch(
        "posthoganalytics.feature_enabled",
        side_effect=lambda key, *_args, **_kwargs: enabled if key == EMAIL_FROM_CODE_FLAG else False,
    )


@override_settings(DOMAIN_CONNECT_PRIVATE_KEY=domain_connect_signing_key_pem(), CLOUD_DEPLOYMENT="US")
class TestEmailSenderScopedAccess(EmailDomainApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.world.domain_connect.host(ROOT_DOMAIN)
        self.sender = self.create_sender(SENDER)
        self.client.logout()

    def credentials(self, authentication: str, scope: str = "integration:write") -> dict[str, Any]:
        if authentication == "session":
            self.client.force_login(self.user)
            return {}
        if authentication == "pak":
            token = "synthetic_sender_key"
            PersonalAPIKey.objects.create(
                user=self.user,
                label="Sender test",
                secure_value=hash_key_value(token),
                scopes=[scope],
                scoped_teams=[self.team.pk],
            )
        else:
            token = "pha_synthetic_sender_token"
            application = OAuthApplication.objects.create(
                user=self.user,
                name="Sender test client",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                algorithm="RS256",
                redirect_uris="https://example.com/callback",
            )
            OAuthAccessToken.objects.create(
                user=self.user,
                application=application,
                token=token,
                expires=timezone.now() + timedelta(hours=1),
                scope=scope,
                scoped_teams=[self.team.pk],
            )
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def update_sender(
        self, changes: dict[str, str], *, sender: int | None = None, team_id: int | None = None, **headers: Any
    ) -> Any:
        return self.client.patch(
            f"/api/projects/{team_id or self.team.id}/integrations/{sender or self.sender}/email",
            {"config": {"email": SENDER, "name": "Example", "provider": "ses", **changes}},
            format="json",
            **headers,
        )

    def apply_url(self, body: dict[str, Any], **headers: Any) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/integrations/domain-connect/apply-url", body, format="json", **headers
        )

    def config(self, sender: int | None = None) -> dict[str, Any]:
        return Integration.objects.get(id=sender or self.sender).config

    def mail_from_domain(self, domain: str = DOMAIN) -> str | None:
        return self.world.ses.identities[domain].mail_from_domain

    @parameterized.expand(
        [
            (f"{authentication}_flag_{flag}", authentication, flag)
            for authentication in ALL_AUTHENTICATIONS
            for flag in (False, True, None)
        ]
    )
    def test_sender_update_needs_the_flag_for_token_callers(
        self, _name: str, authentication: str, flag: bool | None
    ) -> None:
        config_before = self.config()
        changes = {"name": "Updated sender", "mail_from_subdomain": "notifications", "reply_to": "support@example.com"}

        with email_from_code(flag):
            response = self.update_sender(changes, **self.credentials(authentication))

        allowed = bool(flag) or authentication == "session"
        assert response.status_code == (status.HTTP_200_OK if allowed else status.HTTP_403_FORBIDDEN), response.json()
        assert self.config() == ({**config_before, **changes} if allowed else config_before)
        assert self.mail_from_domain() == f"{'notifications' if allowed else 'feedback'}.{DOMAIN}"

    def test_flag_released_to_a_project_id_reaches_the_sender_update(self) -> None:
        def released_to_this_project(key: str, distinct_id: str, **kwargs: Any) -> bool:
            return str(kwargs["group_properties"]["project"]["id"]) == str(self.team.id)

        with patch("posthoganalytics.feature_enabled", side_effect=released_to_this_project):
            response = self.update_sender({"name": "Updated sender"}, **self.credentials("pak"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self.config()["name"] == "Updated sender"

    @parameterized.expand(
        [
            (f"{authentication}_{restriction}", authentication, restriction, expected_status, detail)
            for authentication in TOKEN_AUTHENTICATIONS
            for restriction, expected_status, detail in [
                ("read_scope", status.HTTP_403_FORBIDDEN, "integration:write"),
                ("member", status.HTTP_403_FORBIDDEN, "sufficient permissions"),
                ("foreign_integration", status.HTTP_404_NOT_FOUND, ""),
                ("restricted_project", status.HTTP_403_FORBIDDEN, "requested project"),
                ("readonly_mcp", status.HTTP_403_FORBIDDEN, "read-only"),
            ]
        ]
    )
    def test_sender_update_keeps_access_restrictions(
        self, _name: str, authentication: str, restriction: str, expected_status: int, detail: str
    ) -> None:
        headers = self.credentials(
            authentication, "integration:read" if restriction == "read_scope" else "integration:write"
        )
        sender, team_id = self.sender, self.team.id
        if restriction == "member":
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
        elif restriction in ("foreign_integration", "restricted_project"):
            other_team = Team.objects.create(organization=self.organization)
            if restriction == "foreign_integration":
                sender = Integration.objects.create(team=other_team, kind="email", config=self.config()).id
            else:
                team_id = other_team.id
        elif restriction == "readonly_mcp":
            self.organization.read_only_mcp_access = True
            self.organization.available_product_features = [{"key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}]
            self.organization.save()
        config_before = self.config()

        with email_from_code(True):
            response = self.update_sender(
                {"name": "Denied sender", "mail_from_subdomain": "bounce"},
                sender=sender,
                team_id=team_id,
                HTTP_USER_AGENT="posthog/mcp-server",
                **headers,
            )

        assert response.status_code == expected_status, response.json()
        assert detail in response.json()["detail"]
        assert self.config() == config_before
        assert self.mail_from_domain() == f"feedback.{DOMAIN}"

    @parameterized.expand(
        [
            ("domain_connect_check", "get", "domain-connect/check?domain=mail.example.com"),
            ("domain_connect_apply_url", "post", "domain-connect/apply-url"),
            ("sender_update", "patch", "{sender}/email"),
        ]
    )
    def test_token_access_is_refused_while_the_flag_is_off(self, _name: str, method: str, path: str) -> None:
        with email_from_code(False):
            response = getattr(self.client, method)(
                f"/api/projects/{self.team.id}/integrations/{path.format(sender=self.sender)}",
                format="json",
                **self.credentials("pak"),
            )

        assert (response.status_code, response.json()["detail"]) == (status.HTTP_403_FORBIDDEN, NO_TOKEN_ACCESS)

    @parameterized.expand(
        [
            (
                "member_checks_the_dns_host",
                "get",
                "domain-connect/check?domain=mail.example.com",
                None,
                "integration:read",
                OrganizationMembership.Level.MEMBER,
                status.HTTP_200_OK,
                {"supported": True, "provider_name": "Cloudflare"},
            ),
            (
                "apply_url_needs_write_scope",
                "post",
                "domain-connect/apply-url",
                {"context": "email", "integration_id": "{sender}"},
                "integration:read",
                OrganizationMembership.Level.ADMIN,
                status.HTTP_403_FORBIDDEN,
                {"detail": MISSING_WRITE_SCOPE},
            ),
            (
                "apply_url_needs_a_sender",
                "post",
                "domain-connect/apply-url",
                {"context": "email"},
                "integration:write",
                OrganizationMembership.Level.ADMIN,
                status.HTTP_400_BAD_REQUEST,
                {"detail": "integration_id is required for email context"},
            ),
            (
                "apply_url_for_an_unknown_sender",
                "post",
                "domain-connect/apply-url",
                {"context": "email", "integration_id": 999_999_999},
                "integration:write",
                OrganizationMembership.Level.ADMIN,
                status.HTTP_404_NOT_FOUND,
                {"detail": "Email integration not found."},
            ),
            (
                "apply_url_for_another_kind",
                "post",
                "domain-connect/apply-url",
                {"context": "email", "integration_id": "{other_kind}"},
                "integration:write",
                OrganizationMembership.Level.ADMIN,
                status.HTTP_404_NOT_FOUND,
                {"detail": "Email integration not found."},
            ),
            (
                "verify_another_kind",
                "post",
                "{other_kind}/email/verify",
                None,
                "integration:write",
                OrganizationMembership.Level.ADMIN,
                status.HTTP_400_BAD_REQUEST,
                {"detail": "This endpoint is only supported for email integrations"},
            ),
        ]
    )
    def test_scoped_email_domain_requests(
        self,
        _name: str,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        scope: str,
        level: OrganizationMembership.Level,
        expected_status: int,
        expected_body: dict[str, Any],
    ) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()
        ids = {"{sender}": self.sender, "{other_kind}": Integration.objects.create(team=self.team, kind="slack").id}
        headers = self.credentials("pak", scope)
        if body is not None:
            body = {key: ids.get(value, value) if isinstance(value, str) else value for key, value in body.items()}
        config_before = self.config()

        with email_from_code(True):
            response = getattr(self.client, method)(
                f"/api/projects/{self.team.id}/integrations/{path.format(**{key[1:-1]: v for key, v in ids.items()})}",
                body,
                format="json",
                **headers,
            )

        assert response.status_code == expected_status, response.json()
        assert response.json() == {**response.json(), **expected_body}
        assert self.config() == config_before

    @parameterized.expand(
        [
            (f"{authentication}_flag_{flag}", authentication, flag)
            for authentication in ALL_AUTHENTICATIONS
            for flag in (False, True)
        ]
    )
    def test_proxy_domain_connect_needs_a_session(self, _name: str, authentication: str, flag: bool) -> None:
        proxy = ProxyRecord.objects.create(
            organization=self.organization, domain=f"events.{ROOT_DOMAIN}", target_cname="proxy.example.net"
        )

        with email_from_code(flag):
            response = self.apply_url(
                {"context": "proxy", "proxy_record_id": str(proxy.pk)}, **self.credentials(authentication)
            )

        if authentication == "session":
            assert response.status_code == status.HTTP_200_OK, response.json()
            self.world.domain_connect.apply(response.json()["url"])
            assert self.world.dns.cname_target(f"events.{ROOT_DOMAIN}") == "proxy.example.net"
        else:
            expected_detail = "Scoped credentials only support email Domain Connect." if flag else NO_TOKEN_ACCESS
            assert (response.status_code, response.json()["detail"]) == (status.HTTP_403_FORBIDDEN, expected_detail)
            assert self.world.dns.cname_target(f"events.{ROOT_DOMAIN}") is None

    @parameterized.expand(
        [
            (
                "token_us",
                True,
                "pak",
                "https://us.posthog.com",
                "us.posthog.com",
                "https://us.posthog.com/project/1/channels?dc=email",
                status.HTTP_200_OK,
            ),
            (
                "token_eu",
                True,
                "pak",
                "https://eu.posthog.com",
                "eu.posthog.com",
                "https://eu.posthog.com/project/1/channels?dc=email",
                status.HTTP_200_OK,
            ),
            (
                "token_self_hosted_port",
                True,
                "pak",
                "http://posthog.internal:8010",
                "posthog.internal:8010",
                "http://posthog.internal:8010/channels",
                status.HTTP_200_OK,
            ),
            (
                "token_foreign_host",
                True,
                "pak",
                "https://us.posthog.com",
                "us.posthog.com",
                "https://attacker.example/landing",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                "token_foreign_request_host",
                True,
                "pak",
                "https://us.posthog.com",
                "attacker.example",
                "https://attacker.example/landing",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                "token_scheme_relative",
                True,
                "pak",
                "https://us.posthog.com",
                "us.posthog.com",
                "//attacker.example/landing",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                "token_relative_path",
                True,
                "pak",
                "https://us.posthog.com",
                "us.posthog.com",
                "/project/1/channels",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                "token_javascript",
                True,
                "pak",
                "https://us.posthog.com",
                "us.posthog.com",
                "javascript:alert(1)",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                "session",
                True,
                "session",
                "https://us.posthog.com",
                "us.posthog.com",
                "https://us.posthog.com/channels",
                status.HTTP_200_OK,
            ),
            (
                "session_flag_off",
                False,
                "session",
                "https://us.posthog.com",
                "us.posthog.com",
                "https://us.posthog.com/channels",
                status.HTTP_200_OK,
            ),
            (
                "session_other_site_url",
                True,
                "session",
                "http://localhost:8010",
                "us.posthog.com",
                "https://us.posthog.com/channels",
                status.HTTP_200_OK,
            ),
        ]
    )
    def test_apply_url_for_a_token_only_redirects_back_to_posthog(
        self,
        _name: str,
        flag: bool,
        authentication: str,
        site_url: str,
        request_host: str,
        redirect_uri: str,
        expected_status: int,
    ) -> None:
        config_before = self.config()
        region = "EU" if urlsplit(redirect_uri).hostname == "eu.posthog.com" else "US"

        with email_from_code(flag), self.settings(SITE_URL=site_url, CLOUD_DEPLOYMENT=region):
            response = self.apply_url(
                {"context": "email", "integration_id": self.sender, "redirect_uri": redirect_uri},
                HTTP_HOST=request_host,
                **self.credentials(authentication),
            )

        assert response.status_code == expected_status, response.json()
        if expected_status == status.HTTP_400_BAD_REQUEST:
            assert response.json()["detail"] == REDIRECT_OUTSIDE_POSTHOG
            assert self.config() == config_before
        else:
            assert self.config()["setup_method"] == "auto"
            if urlsplit(redirect_uri).hostname in ("us.posthog.com", "eu.posthog.com"):
                assert self.world.domain_connect.apply(response.json()["url"]) == redirect_uri

    @parameterized.expand(
        [
            (
                "app_with_the_flag_keeps_the_stored_case",
                True,
                "session",
                "Hello@mail.example.com",
                "Hello@mail.example.com",
                status.HTTP_200_OK,
            ),
            (
                "app_without_the_flag_ignores_a_new_address",
                False,
                "session",
                SENDER,
                f"team@{DOMAIN}",
                status.HTTP_200_OK,
            ),
            ("token_cannot_change_the_address", True, "pak", SENDER, f"team@{DOMAIN}", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_sender_update_keeps_the_sender_address(
        self, _name: str, flag: bool, authentication: str, stored_email: str, sent_email: str, expected_status: int
    ) -> None:
        Integration.objects.filter(id=self.sender).update(config={**self.config(), "email": stored_email})

        with email_from_code(flag):
            response = self.update_sender({"email": sent_email, "name": "Acme"}, **self.credentials(authentication))

        assert response.status_code == expected_status, response.json()
        if expected_status == status.HTTP_400_BAD_REQUEST:
            assert response.json()["detail"] == (
                f"The sender address cannot change. Create a new sender for {sent_email} instead."
            )
        assert self.config()["email"] == stored_email
        assert self.config()["name"] == ("Acme" if expected_status == status.HTTP_200_OK else "Example")

    @parameterized.expand(
        [
            ("token_moving_mail_from", "pak", {"mail_from_subdomain": "bounce"}, status.HTTP_403_FORBIDDEN, "feedback"),
            ("token_renaming", "pak", {"name": "Acme Billing"}, status.HTTP_200_OK, "feedback"),
            ("session_moving_mail_from", "session", {"mail_from_subdomain": "bounce"}, status.HTTP_200_OK, "bounce"),
        ]
    )
    def test_token_cannot_move_a_mail_from_shared_with_another_project(
        self, _name: str, authentication: str, changes: dict[str, str], expected_status: int, mail_from: str
    ) -> None:
        self.client.force_login(self.user)
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        other_sender = self.create_sender(f"news@{DOMAIN}", team=other_team)
        self.client.logout()
        config_before = self.config()

        with email_from_code(True):
            response = self.update_sender(changes, **self.credentials(authentication))

        assert response.status_code == expected_status, response.json()
        if expected_status == status.HTTP_403_FORBIDDEN:
            assert response.json()["detail"] == SHARED_MAIL_FROM
            assert self.config() == config_before
        assert self.mail_from_domain() == f"{mail_from}.{DOMAIN}"
        assert self.config(other_sender)["mail_from_subdomain"] == "feedback"

    def test_ses_mail_from_change_holds_off_a_sender_created_on_the_same_domain(self) -> None:
        domain = f"billing.{ROOT_DOMAIN}"
        self.world.ses.add_identity(domain, mail_from_domain=f"feedback.{domain}")
        sender = Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id=f"hello@{domain}",
            config={"email": f"hello@{domain}", "domain": domain, "name": "Example", "provider": "ses"},
        ).id
        write_mail_from = self.world.ses._set_identity_mail_from_domain
        creator_could_proceed: list[bool] = []

        def write_while_a_creator_tries_the_domain(**kwargs: Any) -> dict:
            creator_could_proceed.append(sender_creation_can_lock(domain))
            return write_mail_from(**kwargs)

        with (
            email_from_code(True),
            patch.object(self.world.ses, "_set_identity_mail_from_domain", write_while_a_creator_tries_the_domain),
        ):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/integrations/{sender}/email",
                {
                    "config": {
                        "email": f"hello@{domain}",
                        "name": "Example",
                        "provider": "ses",
                        "mail_from_subdomain": "bounce",
                    }
                },
                format="json",
                **self.credentials("pak"),
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self.mail_from_domain(domain) == f"bounce.{domain}"
        assert creator_could_proceed == [False]


def sender_creation_can_lock(domain: str) -> bool:
    creator = connections.create_connection(DEFAULT_DB_ALIAS)
    try:
        with creator.cursor() as cursor:
            cursor.execute("SET lock_timeout = '100ms'")
            try:
                lock_sender_domain(cursor, domain)
            except OperationalError:
                return False
            return True
    finally:
        creator.close()
