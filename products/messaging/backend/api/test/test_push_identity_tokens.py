from datetime import timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.team.team import Team

from products.messaging.backend.api.push_identity_tokens import sign_push_identity_token, verify_push_identity_token

# Realistic length (>= 32 bytes) — matches a real phs_ secret and avoids PyJWT's short-key warning.
CURRENT_SECRET = "phs_current_secret_0123456789abcdef0123"
BACKUP_SECRET = "phs_backup_secret_0123456789abcdef01234"
DISTINCT_ID = "user-1"
APP_ID = "my-firebase-project"


class TestPushIdentityTokens(SimpleTestCase):
    def _team(self, secret: str | None = CURRENT_SECRET, backup: str | None = None) -> Team:
        return Team(secret_api_token=secret, secret_api_token_backup=backup)

    def test_verifies_a_token_signed_with_the_current_secret(self):
        token = sign_push_identity_token(CURRENT_SECRET, DISTINCT_ID, APP_ID)
        assert verify_push_identity_token(token, self._team(), DISTINCT_ID, APP_ID) is True

    def test_verifies_a_token_signed_with_the_backup_secret_after_rotation(self):
        token = sign_push_identity_token(BACKUP_SECRET, DISTINCT_ID, APP_ID)
        team = self._team(secret=CURRENT_SECRET, backup=BACKUP_SECRET)
        assert verify_push_identity_token(token, team, DISTINCT_ID, APP_ID) is True

    @parameterized.expand(
        [
            ("wrong_distinct_id", "someone-else", APP_ID),
            ("wrong_app_id", DISTINCT_ID, "other-app"),
        ]
    )
    def test_rejects_a_token_whose_claims_do_not_match_the_registration(self, _name, sub, app_id):
        # The rebind guard: a token minted for one (distinct_id, app_id) cannot authorize a different one.
        token = sign_push_identity_token(CURRENT_SECRET, sub, app_id)
        assert verify_push_identity_token(token, self._team(), DISTINCT_ID, APP_ID) is False

    def test_rejects_a_token_signed_with_a_different_secret(self):
        token = sign_push_identity_token("phs_attacker_secret_0123456789abcdef012", DISTINCT_ID, APP_ID)
        assert verify_push_identity_token(token, self._team(), DISTINCT_ID, APP_ID) is False

    def test_rejects_an_expired_token(self):
        token = sign_push_identity_token(CURRENT_SECRET, DISTINCT_ID, APP_ID, ttl=timedelta(seconds=-1))
        assert verify_push_identity_token(token, self._team(), DISTINCT_ID, APP_ID) is False

    def test_rejects_a_malformed_token(self):
        assert verify_push_identity_token("not-a-jwt", self._team(), DISTINCT_ID, APP_ID) is False

    def test_rejects_when_the_team_has_no_secret_configured(self):
        token = sign_push_identity_token(CURRENT_SECRET, DISTINCT_ID, APP_ID)
        assert verify_push_identity_token(token, self._team(secret=None), DISTINCT_ID, APP_ID) is False
