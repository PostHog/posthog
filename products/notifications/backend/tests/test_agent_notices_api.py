from datetime import timedelta
from typing import Any, Optional

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.feature_flags.backend.models import FeatureFlag
from products.notifications.backend.models import AgentNotice


def _create_notice(team: Optional[Team], **kwargs: Any) -> AgentNotice:
    now = timezone.now()
    defaults: dict[str, Any] = {
        "message": "Test notice",
        "starts_at": now - timedelta(hours=1),
        "expires_at": now + timedelta(hours=1),
    }
    defaults.update(kwargs)
    return AgentNotice.objects.unscoped().create(team=team, **defaults)


class TestAgentNoticesAPI(APIBaseTest):
    def _list(self, team_id: Optional[int] = None):
        return self.client.get(f"/api/projects/{team_id or self.team.id}/agent_notices/")

    def test_returns_own_team_and_broadcast_notices_only(self):
        _create_notice(self.team, message="team notice")
        _create_notice(None, message="broadcast notice")
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        _create_notice(other_team, message="other team notice")

        response = self._list()

        assert response.status_code == 200
        assert {n["message"] for n in response.json()} == {"team notice", "broadcast notice"}

    def test_returns_feature_flag_key_for_gated_notices(self):
        flag = FeatureFlag.objects.create(team=self.team, key="data-warehouse-release-december", created_by=self.user)
        _create_notice(self.team, message="gated", feature_flag=flag)
        _create_notice(self.team, message="ungated")

        response = self._list()

        assert response.status_code == 200
        by_message = {n["message"]: n["feature_flag_key"] for n in response.json()}
        assert by_message == {"gated": "data-warehouse-release-december", "ungated": None}

    @parameterized.expand(
        [
            ("not_started_yet", {"starts_at": timedelta(hours=1), "expires_at": timedelta(hours=2)}),
            ("already_expired", {"starts_at": timedelta(hours=-2), "expires_at": timedelta(hours=-1)}),
            ("deactivated", {"is_active": False}),
        ]
    )
    def test_excludes_undeliverable_notices(self, _name: str, overrides: dict[str, Any]):
        now = timezone.now()
        kwargs = {k: now + v if isinstance(v, timedelta) else v for k, v in overrides.items()}
        _create_notice(self.team, **kwargs)

        response = self._list()

        assert response.status_code == 200
        assert response.json() == []

    def test_capped_at_five_newest_first(self):
        now = timezone.now()
        for i in range(7):
            _create_notice(
                self.team,
                message=f"notice {i}",
                starts_at=now - timedelta(minutes=30 - i),
                expires_at=now + timedelta(hours=1),
            )

        response = self._list()

        assert response.status_code == 200
        messages = [n["message"] for n in response.json()]
        assert messages == ["notice 6", "notice 5", "notice 4", "notice 3", "notice 2"]

    def test_non_member_cannot_list_other_team_notices(self):
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        _create_notice(other_team, message="secret")

        response = self._list(other_team.id)

        assert response.status_code in (403, 404)

    def test_unauthenticated_request_is_rejected(self):
        self.client.logout()

        response = self._list()

        assert response.status_code == 401

    @parameterized.expand([("post",), ("patch",), ("delete",)])
    def test_write_methods_not_allowed(self, method: str):
        url = f"/api/projects/{self.team.id}/agent_notices/"
        response = getattr(self.client, method)(url, {}, format="json")

        assert response.status_code == 405

    def _list_with_api_key(self, scopes: list[str], scoped_teams: Optional[list[int]] = None):
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="test",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=scopes,
            scoped_teams=scoped_teams or [],
            scoped_organizations=[],
        )
        self.client.logout()
        return self.client.get(
            f"/api/projects/{self.team.id}/agent_notices/",
            headers={"authorization": f"Bearer {value}"},
        )

    def test_api_key_with_project_read_scope_can_list(self):
        _create_notice(self.team, message="visible")

        response = self._list_with_api_key(scopes=["project:read"])

        assert response.status_code == 200
        assert [n["message"] for n in response.json()] == ["visible"]

    def test_team_scoped_api_key_can_list_its_own_team(self):
        _create_notice(self.team, message="visible")

        response = self._list_with_api_key(scopes=["project:read"], scoped_teams=[self.team.id])

        assert response.status_code == 200
        assert [n["message"] for n in response.json()] == ["visible"]

    def test_api_key_without_project_scope_is_rejected(self):
        response = self._list_with_api_key(scopes=["feature_flag:read"])

        assert response.status_code == 403

    def test_api_key_scoped_to_other_team_is_rejected(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")

        response = self._list_with_api_key(scopes=["project:read"], scoped_teams=[other_team.id])

        assert response.status_code == 403
