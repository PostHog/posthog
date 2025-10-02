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
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_can_create_evaluation_config(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Test Evaluation",
                "description": "Test Description",
                "enabled": True,
                "prompt": "Test prompt",
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Evaluation.objects.count(), 1)

        evaluation_config = Evaluation.objects.first()
        assert evaluation_config is not None
        self.assertEqual(evaluation_config.name, "Test Evaluation")
        self.assertEqual(evaluation_config.description, "Test Description")
        self.assertEqual(evaluation_config.enabled, True)
        self.assertEqual(evaluation_config.prompt, "Test prompt")
        self.assertEqual(len(evaluation_config.conditions), 1)
        self.assertEqual(evaluation_config.conditions[0]["id"], "test-condition")
        self.assertEqual(evaluation_config.team, self.team)
        self.assertEqual(evaluation_config.created_by, self.user)
        self.assertEqual(evaluation_config.deleted, False)

    def test_can_retrieve_list_of_evaluation_configs(self):
        Evaluation.objects.create(name="Evaluation 1", prompt="Prompt 1", team=self.team, created_by=self.user)
        Evaluation.objects.create(name="Evaluation 2", prompt="Prompt 2", team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

        evaluation_names = [evaluation["name"] for evaluation in response.data["results"]]
        self.assertIn("Evaluation 1", evaluation_names)
        self.assertIn("Evaluation 2", evaluation_names)

    def test_can_get_single_evaluation_config(self):
        evaluation_config = Evaluation.objects.create(
            name="Test Evaluation",
            description="Test Description",
            enabled=True,
            prompt="Test prompt",
            conditions=[{"id": "test", "rollout_percentage": 100, "properties": []}],
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Test Evaluation")
        self.assertEqual(response.data["description"], "Test Description")
        self.assertEqual(response.data["enabled"], True)
        self.assertEqual(response.data["prompt"], "Test prompt")

    def test_can_edit_evaluation_config(self):
        evaluation_config = Evaluation.objects.create(
            name="Original Name", prompt="Original prompt", team=self.team, created_by=self.user
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/",
            {
                "name": "Updated Name",
                "description": "Updated Description",
                "enabled": False,
                "prompt": "Updated prompt",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        evaluation_config.refresh_from_db()
        self.assertEqual(evaluation_config.name, "Updated Name")
        self.assertEqual(evaluation_config.description, "Updated Description")
        self.assertEqual(evaluation_config.enabled, False)
        self.assertEqual(evaluation_config.prompt, "Updated prompt")

    def test_delete_method_returns_405(self):
        evaluation_config = Evaluation.objects.create(
            name="Test Evaluation", prompt="Test prompt", team=self.team, created_by=self.user
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_can_search_evaluation_configs(self):
        Evaluation.objects.create(
            name="Accuracy Evaluation",
            description="Tests accuracy",
            prompt="Test prompt",
            team=self.team,
            created_by=self.user,
        )
        Evaluation.objects.create(
            name="Performance Evaluation",
            description="Tests performance",
            prompt="Test prompt",
            team=self.team,
            created_by=self.user,
        )

        # Search by name
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?search=accuracy")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "Accuracy Evaluation")

        # Search by description
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?search=performance")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "Performance Evaluation")

    def test_can_filter_by_enabled_status(self):
        Evaluation.objects.create(
            name="Enabled Evaluation", prompt="Test prompt", enabled=True, team=self.team, created_by=self.user
        )
        Evaluation.objects.create(
            name="Disabled Evaluation", prompt="Test prompt", enabled=False, team=self.team, created_by=self.user
        )

        # Filter for enabled only
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?enabled=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "Enabled Evaluation")

        # Filter for disabled only
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?enabled=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "Disabled Evaluation")

    def test_cannot_access_other_teams_evaluation_configs(self):
        other_team = _setup_team()

        # Create evaluation config for other team
        other_evaluation = Evaluation.objects.create(
            name="Other Team Evaluation",
            prompt="Test prompt",
            team=other_team,
            created_by=self.user,
        )

        # Try to access other team's evaluation config
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/{other_evaluation.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # List should not include other team's evaluation configs
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_validation_requires_name_and_prompt(self):
        # Missing name
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {"prompt": "Test prompt"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "name")

        # Missing prompt
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {"name": "Test Evaluation"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "prompt")

    def test_deleted_evaluation_configs_not_returned(self):
        evaluation_config = Evaluation.objects.create(
            name="Deleted Evaluation",
            prompt="Test prompt",
            team=self.team,
            created_by=self.user,
            deleted=True,
        )

        # Should not appear in list
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

        # Should not be accessible for retrieval
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_conditions_with_property_filters(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Test with Properties",
                "prompt": "Evaluate this",
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
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["conditions"]), 2)
        self.assertEqual(response.data["conditions"][0]["rollout_percentage"], 50)
        self.assertEqual(len(response.data["conditions"][0]["properties"]), 1)
        self.assertEqual(response.data["conditions"][0]["properties"][0]["key"], "$ai_model_name")
