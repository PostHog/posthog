import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from posthog.test.base import NonAtomicAPIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.integration import EMAIL_FROM_CODE_FLAG
from posthog.constants import AvailableFeature
from posthog.models.integration import Integration
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.proxy_record import ProxyRecord
from posthog.models.team import Team
from posthog.models.utils import hash_key_value
from posthog.test.waiting import wait_until

from products.workflows.backend.test.email_domain_api_test_case import (
    DOMAIN,
    ROOT_DOMAIN,
    EmailDomainApi,
    EmailDomainApiTestCase,
    email_domain_settings,
)
from products.workflows.backend.tests.fakes.world import domain_connect_signing_key_pem

SENDER = f"hello@{DOMAIN}"
TOKEN_AUTHENTICATIONS = ["pak", "oauth"]
ALL_AUTHENTICATIONS = [*TOKEN_AUTHENTICATIONS, "session"]
NO_TOKEN_ACCESS = "This action is not available to API keys or OAuth tokens in this project."
MISSING_WRITE_SCOPE = "API key missing required scope 'integration:write'"
NO_ADDRESS = object()
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
                "token_malformed_url",
                True,
                "pak",
                "https://us.posthog.com",
                "us.posthog.com",
                "https://[",
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
        region = "EU" if redirect_uri.startswith("https://eu.posthog.com/") else "US"

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
            (
                "app_with_the_flag_renames_a_sender_stored_without_an_address",
                True,
                "session",
                NO_ADDRESS,
                SENDER,
                status.HTTP_200_OK,
            ),
            (
                "app_with_the_flag_renames_a_sender_stored_with_a_null_address",
                True,
                "session",
                None,
                SENDER,
                status.HTTP_200_OK,
            ),
            (
                "token_cannot_change_a_sender_stored_without_an_address",
                True,
                "pak",
                NO_ADDRESS,
                f"team@{DOMAIN}",
                status.HTTP_400_BAD_REQUEST,
            ),
        ]
    )
    def test_sender_update_keeps_the_sender_address(
        self, _name: str, flag: bool, authentication: str, stored_email: object, sent_email: str, expected_status: int
    ) -> None:
        stored_config = {key: value for key, value in self.config().items() if key != "email"}
        if stored_email is not NO_ADDRESS:
            stored_config["email"] = stored_email
        Integration.objects.filter(id=self.sender).update(config=stored_config)

        with email_from_code(flag):
            response = self.update_sender({"email": sent_email, "name": "Acme"}, **self.credentials(authentication))

        assert response.status_code == expected_status, response.json()
        if expected_status == status.HTTP_400_BAD_REQUEST:
            assert response.json()["detail"] == (
                f"The sender address cannot change. Create a new sender for {sent_email} instead."
            )
        assert self.config().get("email", NO_ADDRESS) == stored_email
        assert self.config()["name"] == ("Acme" if expected_status == status.HTTP_200_OK else "Example")

    @parameterized.expand([("session",), ("pak",)])
    def test_sender_stored_with_another_provider_is_refused_not_a_server_error(self, authentication: str) -> None:
        Integration.objects.filter(id=self.sender).update(config={**self.config(), "provider": "mailjet"})
        config_before = self.config()

        with email_from_code(True):
            response = self.update_sender({"name": "Acme"}, **self.credentials(authentication))

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == (
            "This sender uses an email provider that cannot be updated. Create a new sender instead."
        )
        assert self.config() == config_before

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


class RequestOnItsOwnConnection:
    def __init__(self, send: Callable[[], Any]) -> None:
        self._send = send
        self._response: Any = None
        self._error: BaseException | None = None
        self._finished = threading.Event()
        self._thread = threading.Thread(target=self._run)

    @property
    def started(self) -> bool:
        return self._thread.ident is not None

    def _run(self) -> None:
        try:
            self._response = self._send()
        except BaseException as error:
            self._error = error
        finally:
            connection.close()
            self._finished.set()

    def start_and_let_it_reach_the_domain(self) -> None:
        self._thread.start()
        wait_until(
            lambda: self._finished.is_set() or another_connection_waits_on_this_one(),
            timeout=10,
            message="the second request neither finished nor waited on the first",
        )

    def response(self) -> Any:
        self._thread.join(timeout=10)
        assert not self._thread.is_alive(), "the second request never finished"
        if self._error is not None:
            raise self._error
        return self._response


def another_connection_waits_on_this_one() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE NOT granted AND pg_backend_pid() = ANY(pg_blocking_pids(pid)))"
        )
        return cursor.fetchone()[0]


@email_domain_settings
class TestMailFromChangeRacingSenderCreation(EmailDomainApi, NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @parameterized.expand(
        [
            ("mail_from_change_first", True, status.HTTP_200_OK, "bounce"),
            ("sender_creation_first", False, status.HTTP_403_FORBIDDEN, "feedback"),
        ]
    )
    def test_every_sender_on_the_domain_keeps_the_mail_from_ses_holds(
        self, _name: str, mail_from_change_first: bool, change_status: int, mail_from: str
    ) -> None:
        sender = self.create_sender(SENDER)
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        token_client = self.client_class()

        def change_mail_from() -> Any:
            return token_client.patch(
                f"/api/projects/{self.team.id}/integrations/{sender}/email",
                {"config": {"email": SENDER, "name": "Example", "provider": "ses", "mail_from_subdomain": "bounce"}},
                format="json",
                HTTP_AUTHORIZATION="Bearer admin_key",
            )

        def create_sender_in_other_project() -> Any:
            return self.client.post(
                f"/api/projects/{other_team.id}/integrations",
                {"kind": "email", "config": {"email": f"news@{DOMAIN}", "name": "News", "provider": "ses"}},
                format="json",
            )

        if mail_from_change_first:
            first, second, ses_call = change_mail_from, create_sender_in_other_project, "_set_identity_mail_from_domain"
        else:
            first, second, ses_call = create_sender_in_other_project, change_mail_from, "_verify_domain_identity"
        second_request = RequestOnItsOwnConnection(second)
        call_ses = getattr(self.world.ses, ses_call)

        def let_the_second_request_reach_the_domain(**kwargs: Any) -> Any:
            if not second_request.started:
                second_request.start_and_let_it_reach_the_domain()
            return call_ses(**kwargs)

        with email_from_code(True), patch.object(self.world.ses, ses_call, let_the_second_request_reach_the_domain):
            first_response = first()
            second_response = second_request.response()

        change, creation = (
            (first_response, second_response) if mail_from_change_first else (second_response, first_response)
        )
        assert change.status_code == change_status, change.json()
        assert creation.status_code == status.HTTP_201_CREATED, creation.json()
        assert self.world.ses.identities[DOMAIN].mail_from_domain == f"{mail_from}.{DOMAIN}"
        assert {sender.config["mail_from_subdomain"] for sender in Integration.objects.filter(kind="email")} == {
            mail_from
        }
