from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value


class TestEmailReach(ClickhouseTestMixin, APIBaseTest):
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
        assert response.json() == {"verified_member_count": 2, "project_email_count": 2}

    @parameterized.expand(
        [
            (["hog_flow:read"], 403),
            (["person:read"], 403),
            (["hog_flow:read", "person:read"], 200),
        ]
    )
    def test_requires_workflow_and_person_read_scopes(self, scopes: list[str], expected_status: int) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Email reach preview", user=self.user, secure_value=hash_key_value(key), scopes=scopes
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/email_reach/", headers={"authorization": f"Bearer {key}"}
        )

        assert response.status_code == expected_status, response.content
        if expected_status == 200:
            assert response.json() == {"verified_member_count": 0, "project_email_count": 0}

    def test_cannot_read_another_organizations_counts(self) -> None:
        organization = Organization.objects.create(name="Other organization")
        team = Team.objects.create(organization=organization)

        response = self.client.get(f"/api/projects/{team.id}/hog_flows/email_reach/")

        assert response.status_code == 403, response.content
