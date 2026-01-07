from uuid import uuid4

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Organization, Project, Team, User

from products.llm_analytics.backend.models.evaluations import Evaluation


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
    User.objects.create_and_join(org, "test-evaluations@posthog.com", "testpassword123")
    return team


class TestEvaluationConfigsApi(APIBaseTest):
    def test_unauthenticated_user_cannot_access_evaluation_configs(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_can_create_evaluation_config(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Test Evaluation",
                "description": "Test Description",
                "enabled": True,
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert Evaluation.objects.count() == 1

        evaluation_config = Evaluation.objects.first()
        assert evaluation_config is not None
        assert evaluation_config.name == "Test Evaluation"
        assert evaluation_config.description == "Test Description"
        assert evaluation_config.enabled
        assert evaluation_config.evaluation_type == "llm_judge"
        assert evaluation_config.evaluation_config == {"prompt": "Test prompt"}
        assert evaluation_config.output_type == "boolean"
        assert evaluation_config.output_config == {}
        assert len(evaluation_config.conditions) == 1
        assert evaluation_config.conditions[0]["id"] == "test-condition"
        assert evaluation_config.team == self.team
        assert evaluation_config.created_by == self.user
        assert not evaluation_config.deleted

    def test_can_retrieve_list_of_evaluation_configs(self):
        Evaluation.objects.create(
            name="Evaluation 1",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Prompt 1"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
        )
        Evaluation.objects.create(
            name="Evaluation 2",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Prompt 2"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2

        evaluation_names = [evaluation["name"] for evaluation in response.data["results"]]
        assert "Evaluation 1" in evaluation_names
        assert "Evaluation 2" in evaluation_names

    def test_can_get_single_evaluation_config(self):
        evaluation_config = Evaluation.objects.create(
            name="Test Evaluation",
            description="Test Description",
            enabled=True,
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            conditions=[{"id": "test", "rollout_percentage": 100, "properties": []}],
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Test Evaluation"
        assert response.data["description"] == "Test Description"
        assert response.data["enabled"]
        assert response.data["evaluation_type"] == "llm_judge"
        assert response.data["evaluation_config"] == {"prompt": "Test prompt"}

    def test_can_edit_evaluation_config(self):
        evaluation_config = Evaluation.objects.create(
            name="Original Name",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Original prompt"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/",
            {
                "name": "Updated Name",
                "description": "Updated Description",
                "enabled": False,
                "evaluation_config": {"prompt": "Updated prompt"},
            },
        )
        assert response.status_code == status.HTTP_200_OK

        evaluation_config.refresh_from_db()
        assert evaluation_config.name == "Updated Name"
        assert evaluation_config.description == "Updated Description"
        assert not evaluation_config.enabled
        assert evaluation_config.evaluation_config == {"prompt": "Updated prompt"}

    def test_delete_method_returns_405(self):
        evaluation_config = Evaluation.objects.create(
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_can_search_evaluation_configs(self):
        Evaluation.objects.create(
            name="Accuracy Evaluation",
            description="Tests accuracy",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
        )
        Evaluation.objects.create(
            name="Performance Evaluation",
            description="Tests performance",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
        )

        # Search by name
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?search=accuracy")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Accuracy Evaluation"

        # Search by description
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?search=performance")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Performance Evaluation"

    def test_can_filter_by_enabled_status(self):
        Evaluation.objects.create(
            name="Enabled Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            team=self.team,
            created_by=self.user,
        )
        Evaluation.objects.create(
            name="Disabled Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=False,
            team=self.team,
            created_by=self.user,
        )

        # Filter for enabled only
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?enabled=true")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Enabled Evaluation"

        # Filter for disabled only
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?enabled=false")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Disabled Evaluation"

    def test_cannot_access_other_teams_evaluation_configs(self):
        other_team = _setup_team()

        # Create evaluation config for other team
        other_evaluation = Evaluation.objects.create(
            name="Other Team Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            team=other_team,
            created_by=self.user,
        )

        # Try to access other team's evaluation config
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/{other_evaluation.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # List should not include other team's evaluation configs
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

    def test_validation_requires_required_fields(self):
        # Missing name
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["attr"] == "name"

        # Missing evaluation_type
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Test Evaluation",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["attr"] == "evaluation_type"

        # Empty evaluation_config should fail validation
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Test Evaluation",
                "evaluation_type": "llm_judge",
                "evaluation_config": {},
                "output_type": "boolean",
                "output_config": {},
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["attr"] == "config"

    def test_deleted_evaluation_configs_not_returned(self):
        evaluation_config = Evaluation.objects.create(
            name="Deleted Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
            deleted=True,
        )

        # Should not appear in list
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

        # Should not be accessible for retrieval
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_conditions_with_property_filters(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Test with Properties",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Evaluate this"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [
                    {
                        "id": "cond-1",
                        "rollout_percentage": 50,
                        "properties": [
                            {"key": "$ai_model_name", "value": "gpt-4", "operator": "exact", "type": "event"}
                        ],
                    },
                    {
                        "id": "cond-2",
                        "rollout_percentage": 100,
                        "properties": [
                            {"key": "custom_property", "value": "test_value", "operator": "exact", "type": "event"}
                        ],
                    },
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["conditions"]) == 2
        assert response.data["conditions"][0]["rollout_percentage"] == 50
        assert len(response.data["conditions"][0]["properties"]) == 1
        assert response.data["conditions"][0]["properties"][0]["key"] == "$ai_model_name"
