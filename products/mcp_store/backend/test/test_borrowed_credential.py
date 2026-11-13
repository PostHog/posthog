from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, find_oauth_access_token, mint_oauth_access_token
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.mcp_store.backend.borrowed_credential import BorrowedCredentialRefused, confine_borrowed_credential


class TestConfineBorrowedCredential(BaseTest):
    def setUp(self):
        super().setUp()
        self.application = OAuthApplication.objects.create(
            name="MCP store client",
            client_id="mcp-store-test-client",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://app.example.com/callback",
            algorithm="RS256",
        )
        other_org = Organization.objects.create(name="Other org")
        self.other_team = Team.objects.create(organization=other_org, name="Other team")

    def _oauth_token(self, scoped_teams: list[int]) -> str:
        return mint_oauth_access_token(
            application=self.application,
            user=self.user,
            scope="project:read query:read",
            lifetime=timedelta(hours=1),
            scoped_teams=scoped_teams,
        ).token

    def _personal_api_key(self, scoped_teams: list[int] | None) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label="mcp", secure_value=hash_key_value(value), scoped_teams=scoped_teams
        )
        return value

    def test_unscoped_oauth_token_is_swapped_for_one_limited_to_the_project(self):
        original = self._oauth_token(scoped_teams=[])

        confined = confine_borrowed_credential(original, self.team.id)

        assert confined is not None and confined != original
        row = find_oauth_access_token(confined)
        assert row is not None
        assert (row.user_id, row.application_id, row.scope, row.scoped_teams) == (
            self.user.id,
            self.application.id,
            "project:read query:read",
            [self.team.id],
        )
        assert row.expires <= timezone.now() + timedelta(minutes=15)

    def test_confined_token_is_reused_while_it_has_time_left(self):
        original = self._oauth_token(scoped_teams=[])

        first = confine_borrowed_credential(original, self.team.id)
        second = confine_borrowed_credential(original, self.team.id)

        assert first == second
        assert OAuthAccessToken.objects.filter(user=self.user, scoped_teams=[self.team.id]).count() == 1

    def test_oauth_token_already_limited_to_the_project_is_forwarded_unchanged(self):
        original = self._oauth_token(scoped_teams=[self.team.id])

        assert confine_borrowed_credential(original, self.team.id) == original

    def test_project_scoped_personal_api_key_is_forwarded_unchanged(self):
        key = self._personal_api_key(scoped_teams=[self.team.id])

        assert confine_borrowed_credential(key, self.team.id) == key

    @parameterized.expand(
        [
            ("oauth_token_for_another_project", "oauth_other_team"),
            ("oauth_token_from_another_instance", "unknown_oauth"),
            ("unscoped_personal_api_key", "pak_unscoped"),
            ("personal_api_key_spanning_projects", "pak_two_teams"),
            ("personal_api_key_from_another_instance", "unknown_pak"),
        ]
    )
    def test_posthog_credentials_that_cannot_be_limited_are_refused(self, _name: str, kind: str):
        token = {
            "oauth_other_team": lambda: self._oauth_token(scoped_teams=[self.other_team.id]),
            "unknown_oauth": lambda: "pha_" + "x" * 40,
            "pak_unscoped": lambda: self._personal_api_key(scoped_teams=None),
            "pak_two_teams": lambda: self._personal_api_key(scoped_teams=[self.team.id, self.other_team.id]),
            "unknown_pak": lambda: "phx_" + "x" * 40,
        }[kind]()

        with self.assertRaises(BorrowedCredentialRefused):
            confine_borrowed_credential(token, self.team.id)

    def test_third_party_token_is_left_alone(self):
        assert confine_borrowed_credential("sk-linear-abc123", self.team.id) is None
