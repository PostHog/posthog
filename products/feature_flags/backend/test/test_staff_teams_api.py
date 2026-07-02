from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team


class TestFeatureFlagsStaffTeamSearchAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def test_non_staff_user_gets_403(self):
        self.user.is_staff = False
        self.user.save()

        response = self.client.get("/api/feature_flags_staff_teams/?search=Test")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_find_team_in_organization_they_do_not_belong_to(self):
        # The whole point of this endpoint: staff must reach teams they aren't a member of.
        # This guards against someone reintroducing membership scoping (an org filter or
        # TeamAndOrgViewSetMixin) on the viewset.
        other_org = Organization.objects.create(name="Unrelated Org")
        other_team = Team.objects.create(organization=other_org, name="Cross Org Team")
        self.assertFalse(self.user.organization_memberships.filter(organization=other_org).exists())

        response = self.client.get("/api/feature_flags_staff_teams/?search=Cross Org Team")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        returned_ids = [team["id"] for team in response.json()["results"]]
        self.assertIn(other_team.id, returned_ids)

    @parameterized.expand(
        [
            ("exact_id", lambda self: str(self.searchable_team.id)),
            ("padded_exact_id", lambda self: f" {self.searchable_team.id} "),
            ("partial_name", lambda self: "Searchable"),
            ("exact_api_token", lambda self: self.searchable_team.api_token),
            ("partial_org_name", lambda self: "Findable"),
        ]
    )
    def test_search_matches_by_field(self, _name, search_value_fn):
        org = Organization.objects.create(name="Findable Organization")
        self.searchable_team = Team.objects.create(organization=org, name="Searchable Team")

        response = self.client.get("/api/feature_flags_staff_teams/", {"search": search_value_fn(self)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        returned_ids = [team["id"] for team in response.json()["results"]]
        self.assertIn(self.searchable_team.id, returned_ids)

    def test_result_shape(self):
        org = Organization.objects.create(name="Shape Org")
        team = Team.objects.create(organization=org, name="Shape Team")

        response = self.client.get("/api/feature_flags_staff_teams/", {"search": "Shape Team"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        result = next(r for r in response.json()["results"] if r["id"] == team.id)
        self.assertEqual(result["name"], "Shape Team")
        self.assertEqual(result["api_token"], team.api_token)
        self.assertEqual(result["organization_id"], str(org.id))
        self.assertEqual(result["organization_name"], "Shape Org")
        self.assertEqual(result["project_id"], team.project_id)

    @parameterized.expand([("single_letter", "a"), ("empty", "")])
    def test_non_numeric_search_below_min_length_returns_400(self, _name, search):
        # A single-digit numeric id lookup is allowed (see exact_id case above); a single
        # letter or empty string is not, so an over-broad query never returns half the table.
        response = self.client.get("/api/feature_flags_staff_teams/", {"search": search})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_limit_is_capped(self):
        response = self.client.get("/api/feature_flags_staff_teams/", {"search": "Test", "limit": 1000})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_limit_bounds_number_of_results(self):
        org = Organization.objects.create(name="Bulk Org")
        for i in range(3):
            Team.objects.create(organization=org, name=f"Bulk Team {i}")

        response = self.client.get("/api/feature_flags_staff_teams/", {"search": "Bulk Team", "limit": 2})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)
