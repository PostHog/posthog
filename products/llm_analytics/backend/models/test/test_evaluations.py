from posthog.test.base import BaseTest
from unittest.mock import patch

from products.llm_analytics.backend.models.evaluations import Evaluation


class TestEvaluationModel(BaseTest):
    def test_compiles_bytecode_for_conditions_with_properties(self):
        """
        Evaluations should compile bytecode for conditions with properties on save
        """
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[
                {
                    "id": "cond-1",
                    "rollout_percentage": 100,
                    "properties": [
                        {"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}
                    ],
                }
            ],
        )

        evaluation.refresh_from_db()

        self.assertEqual(len(evaluation.conditions), 1)
        self.assertIn("bytecode", evaluation.conditions[0])
        self.assertIsNotNone(evaluation.conditions[0]["bytecode"])
        self.assertIsInstance(evaluation.conditions[0]["bytecode"], list)

    def test_sets_bytecode_error_when_compilation_fails(self):
        """
        If bytecode compilation fails, the bytecode_error field should be set
        """
        with patch("posthog.cdp.filters.compile_filters_bytecode") as mock_compile:
            mock_compile.return_value = {"bytecode": None, "bytecode_error": "Invalid property filter"}

            evaluation = Evaluation.objects.create(
                team=self.team,
                name="Test Evaluation",
                evaluation_type="llm_judge",
                evaluation_config={"prompt": "Test prompt"},
                output_type="boolean",
                output_config={},
                enabled=True,
                created_by=self.user,
                conditions=[
                    {
                        "id": "cond-1",
                        "rollout_percentage": 100,
                        "properties": [{"key": "invalid"}],
                    }
                ],
            )

            evaluation.refresh_from_db()

            self.assertEqual(len(evaluation.conditions), 1)
            self.assertIn("bytecode_error", evaluation.conditions[0])
            self.assertEqual(evaluation.conditions[0]["bytecode_error"], "Invalid property filter")

    def test_handles_empty_properties_list(self):
        """
        Conditions with empty properties should still be saved correctly
        """
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[
                {
                    "id": "cond-1",
                    "rollout_percentage": 100,
                    "properties": [],
                }
            ],
        )

        evaluation.refresh_from_db()

        self.assertEqual(len(evaluation.conditions), 1)
        self.assertEqual(evaluation.conditions[0]["properties"], [])
        self.assertIn("bytecode", evaluation.conditions[0])

    def test_compiles_bytecode_for_multiple_conditions(self):
        """
        All conditions should have their bytecode compiled independently
        """
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[
                {
                    "id": "cond-1",
                    "rollout_percentage": 100,
                    "properties": [
                        {"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}
                    ],
                },
                {
                    "id": "cond-2",
                    "rollout_percentage": 50,
                    "properties": [{"key": "name", "value": "test", "operator": "exact", "type": "person"}],
                },
            ],
        )

        evaluation.refresh_from_db()

        self.assertEqual(len(evaluation.conditions), 2)
        self.assertIn("bytecode", evaluation.conditions[0])
        self.assertIn("bytecode", evaluation.conditions[1])
        self.assertIsNotNone(evaluation.conditions[0]["bytecode"])
        self.assertIsNotNone(evaluation.conditions[1]["bytecode"])

    @patch("posthog.plugins.plugin_server_api.reload_evaluations_on_workers")
    def test_sends_reload_signal_on_save(self, mock_reload):
        """
        Django signal should trigger reload on workers when evaluation is saved
        """
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
        )

        mock_reload.assert_called_once_with(team_id=self.team.id, evaluation_ids=[str(evaluation.id)])

    @patch("posthog.plugins.plugin_server_api.reload_evaluations_on_workers")
    def test_sends_reload_signal_on_update(self, mock_reload):
        """
        Django signal should trigger reload on workers when evaluation is updated
        """
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Original Name",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
        )

        mock_reload.reset_mock()

        evaluation.name = "Updated Name"
        evaluation.save()

        mock_reload.assert_called_once_with(team_id=self.team.id, evaluation_ids=[str(evaluation.id)])

    def test_preserves_other_condition_fields(self):
        """
        Other condition fields (id, rollout_percentage) should be preserved during save
        """
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[
                {
                    "id": "my-custom-id",
                    "rollout_percentage": 75,
                    "properties": [],
                }
            ],
        )

        evaluation.refresh_from_db()

        self.assertEqual(evaluation.conditions[0]["id"], "my-custom-id")
        self.assertEqual(evaluation.conditions[0]["rollout_percentage"], 75)
