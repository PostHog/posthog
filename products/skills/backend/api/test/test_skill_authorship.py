from posthog.test.base import BaseTest

from django.contrib.sessions.backends.db import SessionStore
from django.core.signing import TimestampSigner
from django.test import RequestFactory

from loginas import settings as la_settings
from parameterized import parameterized

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.models import User
from posthog.models.oauth import OAuthAccessToken

from ...api.skill_authorship import resolve_skill_authorship


class TestResolveSkillAuthorship(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.operator = User.objects.create_user(
            email="operator@posthog.com", password="12345678", first_name="Operator"
        )

    def _request(self, *, session_operator: User | None = None, oauth_operator: User | None = None):
        request = RequestFactory().post("/")
        request.session = SessionStore()
        if session_operator is not None:
            request.session[la_settings.USER_SESSION_FLAG] = TimestampSigner().sign(str(session_operator.pk))
        if oauth_operator is not None:
            authenticator = OAuthAccessTokenAuthentication()
            # Unsaved instance: only the impersonation FK is read, and assigning it sets
            # `impersonated_by_id` too, which is what `is_impersonated` checks.
            authenticator.access_token = OAuthAccessToken(impersonated_by=oauth_operator)
            request.successful_authenticator = authenticator  # type: ignore[attr-defined]
        return request

    @parameterized.expand(
        [
            ("browser_session", "session"),
            ("oauth_token", "oauth"),
        ]
    )
    def test_impersonated_request_credits_the_operator(self, _label: str, route: str) -> None:
        request = self._request(
            session_operator=self.operator if route == "session" else None,
            oauth_operator=self.operator if route == "oauth" else None,
        )

        authorship = resolve_skill_authorship(request, requesting_user=self.user)

        assert authorship.provenance == "posthog"
        assert authorship.created_by == self.operator

    def test_ordinary_request_is_team_authored(self) -> None:
        authorship = resolve_skill_authorship(self._request(), requesting_user=self.user)

        assert authorship.provenance == ""
        assert authorship.created_by == self.user

    def test_impersonated_request_with_unrecoverable_operator_is_team_authored(self) -> None:
        request = self._request()
        request.session[la_settings.USER_SESSION_FLAG] = "not-a-valid-signed-pk"

        authorship = resolve_skill_authorship(request, requesting_user=self.user)

        assert authorship.provenance == ""
        assert authorship.created_by == self.user
