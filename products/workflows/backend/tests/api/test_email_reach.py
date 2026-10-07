from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Integration, Organization, OrganizationMembership, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.event_definitions.backend.models.property_definition import PropertyDefinition


class TestEmailReach(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch("posthog.cdp.flag_gated_templates.posthoganalytics.feature_enabled", return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    @parameterized.expand([("off", False, None), ("unavailable", None, RuntimeError("Flag service unavailable"))])
    def test_disabled_reach_is_unavailable_without_count_queries(
        self, name: str, enabled: bool | None, error: Exception | None
    ) -> None:
        with (
            patch(
                "posthog.cdp.flag_gated_templates.posthoganalytics.feature_enabled",
                return_value=enabled,
                side_effect=error,
            ),
            patch("products.workflows.backend.services.email_reach.execute_hogql_query") as query,
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/email_reach/")

        assert response.status_code == 403, response.content
        assert "project_email_count" not in response.json()
        query.assert_not_called()

    def test_reach_is_unavailable_when_email_is_restricted_for_the_caller(self) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        email = PropertyDefinition.objects.create(team=self.team, name="email", type=PropertyDefinition.Type.PERSON)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.user)
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=email,
            organization_member=membership,
            access_level=PropertyAccessLevel.NONE.value,
        )
        _create_person(team=self.team, distinct_ids=["restricted-person"], properties={"email": "hidden@example.com"})
        flush_persons_and_events()

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/email_reach/")

        assert response.status_code == 403, response.content
        assert "project_email_count" not in response.json()

    def test_identifies_senders_without_exposing_config_or_other_teams(self) -> None:
        senders = [
            Integration.objects.create(
                team=self.team,
                kind="email",
                config={"provider": provider, "verified": verified, "domain": "example.com"},
                sensitive_config={"token": "obviously-fake-token"},
            )
            for provider, verified in [("sandbox", True), ("ses", True), ("ses", False), ("maildev", True)]
        ]
        other_team = Team.objects.create(organization=self.organization)
        Integration.objects.create(team=other_team, kind="email", config={"provider": "ses", "verified": True})

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/email_reach/")

        assert response.status_code == 200, response.content
        assert response.json() == {
            "verified_member_count": 0,
            "project_email_count": 0,
            "email_senders": [
                {"integration_id": senders[0].id, "provider": "sandbox", "is_verified": True},
                {"integration_id": senders[1].id, "provider": "ses", "is_verified": True},
                {"integration_id": senders[2].id, "provider": "ses", "is_verified": False},
                {"integration_id": senders[3].id, "provider": "maildev", "is_verified": True},
            ],
        }

    def test_counts_sender_eligible_members_and_project_people_with_email(self) -> None:
        self.user.is_email_verified = True
        self.user.save()
        for index, verified, active in [(1, True, True), (2, False, True), (3, None, True), (4, True, False)]:
            member = User.objects.create(
                email=f"teammate-{index}@example.com", is_email_verified=verified, is_active=active
            )
            OrganizationMembership.objects.create(organization=self.organization, user=member)
        other_organization = Organization.objects.create(name="Other organization")
        outsider = User.objects.create(email="outsider@example.com", is_email_verified=True)
        OrganizationMembership.objects.create(organization=other_organization, user=outsider)
        other_team = Team.objects.create(organization=other_organization)
        for index, properties in enumerate(
            [{"email": "one@example.com"}, {"email": "two@example.com"}, {"email": ""}, {"email": "  "}, {}]
        ):
            _create_person(team=self.team, distinct_ids=[f"person-{index}"], properties=properties)
        _create_person(team=other_team, distinct_ids=["other-person"], properties={"email": "other@example.com"})
        flush_persons_and_events()

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/email_reach/")

        assert response.status_code == 200, response.content
        assert response.json() == {"verified_member_count": 2, "project_email_count": 2, "email_senders": []}

    @parameterized.expand(
        [
            (["hog_flow:read"], 403),
            (["person:read"], 403),
            (["hog_flow:read", "person:read"], 403),
            (["hog_flow:read", "integration:read"], 403),
            (["person:read", "integration:read"], 403),
            (["hog_flow:read", "person:read", "integration:read"], 200),
        ]
    )
    def test_requires_workflow_person_and_integration_read_scopes(
        self, scopes: list[str], expected_status: int
    ) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Email reach preview", user=self.user, secure_value=hash_key_value(key), scopes=scopes
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/email_reach/", headers={"authorization": f"Bearer {key}"}
        )

        assert response.status_code == expected_status, response.content
        if expected_status == 200:
            assert response.json() == {"verified_member_count": 0, "project_email_count": 0, "email_senders": []}

    def test_cannot_read_another_organizations_counts(self) -> None:
        organization = Organization.objects.create(name="Other organization")
        team = Team.objects.create(organization=organization)

        response = self.client.get(f"/api/projects/{team.id}/hog_flows/email_reach/")

        assert response.status_code == 403, response.content
