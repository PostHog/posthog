from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team, User


class TestLogsCustomFacetsAPI(APIBaseTest):
    base_url: str

    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/logs/custom_facets/"

    def _facets(self, *pairs: tuple[str, str]) -> list[dict]:
        return [{"key": key, "attribute_type": attribute_type} for key, attribute_type in pairs]

    def test_get_is_empty_when_unconfigured(self):
        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_set_then_get_round_trips(self):
        facets = self._facets(("k8s.namespace.name", "resource"), ("http.status_code", "log"))

        post = self.client.post(self.base_url, facets, format="json")
        assert post.status_code == status.HTTP_200_OK, post.json()
        assert post.json() == facets

        assert self.client.get(self.base_url).json() == facets

    def test_set_replaces_the_whole_set(self):
        self.client.post(self.base_url, self._facets(("a", "log")), format="json")
        self.client.post(self.base_url, self._facets(("b", "resource")), format="json")

        assert self.client.get(self.base_url).json() == self._facets(("b", "resource"))

    def test_duplicates_are_collapsed_on_write(self):
        payload = self._facets(("a", "log"), ("a", "log"), ("b", "resource"))

        post = self.client.post(self.base_url, payload, format="json")
        assert post.json() == self._facets(("a", "log"), ("b", "resource"))

    @parameterized.expand(
        [
            ("invalid_attribute_type", [{"key": "a", "attribute_type": "bogus"}]),
            ("blank_key", [{"key": "", "attribute_type": "log"}]),
            ("missing_key", [{"attribute_type": "log"}]),
            ("over_cap", [{"key": f"k{i}", "attribute_type": "log"} for i in range(51)]),
        ]
    )
    def test_rejects_invalid_payload(self, _label, payload):
        response = self.client.post(self.base_url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_config_is_isolated_per_user(self):
        mine = self._facets(("mine", "log"))
        self.client.post(self.base_url, mine, format="json")

        other = User.objects.create_and_join(self.organization, "other@posthog.com", "secret")
        self.client.force_login(other)
        # The other user starts empty and can't see mine.
        assert self.client.get(self.base_url).json() == []
        theirs = self._facets(("theirs", "resource"))
        self.client.post(self.base_url, theirs, format="json")
        assert self.client.get(self.base_url).json() == theirs

        # Mine is untouched by their write.
        self.client.force_login(self.user)
        assert self.client.get(self.base_url).json() == mine

    def test_config_is_isolated_per_project(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        self.client.post(self.base_url, self._facets(("team1", "log")), format="json")

        response = self.client.get(f"/api/projects/{team2.pk}/logs/custom_facets/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
