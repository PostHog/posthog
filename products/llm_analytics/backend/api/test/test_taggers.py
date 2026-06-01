from uuid import uuid4

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Project, Team, User

from products.llm_analytics.backend.models.taggers import Tagger, TaggerType


def _setup_team():
    org = Organization.objects.create(name="test")
    project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=org)
    team = Team.objects.create(
        id=project.id,
        project=project,
        organization=org,
        api_token=str(uuid4()),
        test_account_filters=[
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ],
        has_completed_onboarding_for={"product_analytics": True},
    )
    User.objects.create_and_join(org, "test-taggers@posthog.com", "testpassword123")
    return team


def _make_tagger_config(**overrides):
    defaults = {
        "prompt": "Which product features were discussed?",
        "tags": [
            {"name": "billing", "description": "Billing related"},
            {"name": "analytics", "description": "Analytics related"},
        ],
        "min_tags": 0,
        "max_tags": 2,
    }
    return {**defaults, **overrides}


class TestTaggersApi(APIBaseTest):
    def test_unauthenticated_user_cannot_access_taggers(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/taggers/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_can_create_tagger(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/taggers/",
            {
                "name": "Feature Tagger",
                "description": "Tags product features",
                "enabled": True,
                "tagger_config": _make_tagger_config(),
                "conditions": [{"id": "cond-1", "rollout_percentage": 50, "properties": []}],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert Tagger.objects.count() == 1

        tagger = Tagger.objects.first()
        assert tagger is not None
        assert tagger.name == "Feature Tagger"
        assert tagger.description == "Tags product features"
        assert tagger.enabled is True
        assert tagger.tagger_config["prompt"] == "Which product features were discussed?"
        assert len(tagger.tagger_config["tags"]) == 2
        assert len(tagger.conditions) == 1
        assert tagger.conditions[0]["id"] == "cond-1"
        assert tagger.team == self.team
        assert tagger.created_by == self.user
        assert tagger.deleted is False

    def test_can_retrieve_list_of_taggers(self):
        Tagger.objects.create(
            name="Tagger 1",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )
        Tagger.objects.create(
            name="Tagger 2",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/taggers/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2

        names = [t["name"] for t in response.data["results"]]
        assert "Tagger 1" in names
        assert "Tagger 2" in names

    def test_can_get_single_tagger(self):
        tagger = Tagger.objects.create(
            name="Test Tagger",
            description="Test desc",
            enabled=True,
            tagger_config=_make_tagger_config(),
            conditions=[{"id": "test", "rollout_percentage": 100, "properties": []}],
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/taggers/{tagger.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Test Tagger"
        assert response.data["description"] == "Test desc"
        assert response.data["enabled"] is True
        assert response.data["tagger_config"]["prompt"] == "Which product features were discussed?"

    def test_can_edit_tagger(self):
        tagger = Tagger.objects.create(
            name="Original Name",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/taggers/{tagger.id}/",
            {
                "name": "Updated Name",
                "description": "Updated desc",
                "enabled": False,
                "tagger_config": _make_tagger_config(prompt="Updated prompt"),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        tagger.refresh_from_db()
        assert tagger.name == "Updated Name"
        assert tagger.description == "Updated desc"
        assert tagger.enabled is False
        assert tagger.tagger_config["prompt"] == "Updated prompt"

    def test_delete_method_returns_405(self):
        tagger = Tagger.objects.create(
            name="Test Tagger",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/taggers/{tagger.id}/")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_soft_delete_via_patch(self):
        tagger = Tagger.objects.create(
            name="Test Tagger",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/taggers/{tagger.id}/",
            {"deleted": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        tagger.refresh_from_db()
        assert tagger.deleted is True

        # Soft-deleted taggers should not appear in list
        response = self.client.get(f"/api/environments/{self.team.id}/taggers/")
        assert len(response.data["results"]) == 0

    def test_can_search_taggers(self):
        Tagger.objects.create(
            name="Feature Tagger",
            description="Tags features",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )
        Tagger.objects.create(
            name="Intent Classifier",
            description="Classifies intent",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )

        # Search by name
        response = self.client.get(f"/api/environments/{self.team.id}/taggers/?search=feature")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Feature Tagger"

        # Search by description
        response = self.client.get(f"/api/environments/{self.team.id}/taggers/?search=intent")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Intent Classifier"

    def test_can_filter_by_enabled_status(self):
        Tagger.objects.create(
            name="Enabled Tagger",
            tagger_config=_make_tagger_config(),
            enabled=True,
            team=self.team,
            created_by=self.user,
        )
        Tagger.objects.create(
            name="Disabled Tagger",
            tagger_config=_make_tagger_config(),
            enabled=False,
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/taggers/?enabled=true")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Enabled Tagger"

        response = self.client.get(f"/api/environments/{self.team.id}/taggers/?enabled=false")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Disabled Tagger"

    def test_cannot_access_other_teams_taggers(self):
        other_team = _setup_team()

        other_tagger = Tagger.objects.create(
            name="Other Team Tagger",
            tagger_config=_make_tagger_config(),
            team=other_team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/taggers/{other_tagger.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        response = self.client.get(f"/api/environments/{self.team.id}/taggers/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

    def test_validation_requires_name(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/taggers/",
            {
                "tagger_config": _make_tagger_config(),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_validation_requires_tagger_config(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/taggers/",
            {
                "name": "Test",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("empty_tags", {"tags": []}),
            (
                "duplicate_tag_names",
                {
                    "tags": [
                        {"name": "billing", "description": ""},
                        {"name": "billing", "description": ""},
                    ]
                },
            ),
            ("min_tags_greater_than_max_tags", {"min_tags": 5, "max_tags": 2}),
            ("max_tags_greater_than_tag_count", {"max_tags": 10}),
        ]
    )
    def test_validation_rejects_invalid_tagger_config(self, _name: str, config_overrides: dict):
        response = self.client.post(
            f"/api/environments/{self.team.id}/taggers/",
            {
                "name": "Test",
                "tagger_config": _make_tagger_config(**config_overrides),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_patch_tagger_type_without_fresh_config_is_rejected(self):
        tagger = Tagger.objects.create(
            name="LLM tagger",
            tagger_type=TaggerType.LLM,
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/taggers/{tagger.id}/",
            {"tagger_type": TaggerType.HOG},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "tagger_config"
