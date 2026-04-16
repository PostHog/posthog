from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.exceptions import ValidationError

from parameterized import parameterized

from products.llm_analytics.backend.models.evaluations import Evaluation, EvaluationStatus, EvaluationStatusReason


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

    def test_hog_evaluation_compiles_source_to_bytecode(self):
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Hog Eval",
            evaluation_type="hog",
            evaluation_config={"source": "return true"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
        )

        evaluation.refresh_from_db()

        self.assertIn("bytecode", evaluation.evaluation_config)
        self.assertIsInstance(evaluation.evaluation_config["bytecode"], list)
        self.assertTrue(len(evaluation.evaluation_config["bytecode"]) > 0)

    def test_hog_evaluation_invalid_source_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            Evaluation.objects.create(
                team=self.team,
                name="Bad Hog Eval",
                evaluation_type="hog",
                evaluation_config={"source": "this is not valid hog {{{{"},
                output_type="boolean",
                output_config={},
                enabled=True,
                created_by=self.user,
                conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
            )

    def test_hog_evaluation_empty_source_rejected(self):
        with self.assertRaises(ValidationError):
            Evaluation.objects.create(
                team=self.team,
                name="Empty Hog Eval",
                evaluation_type="hog",
                evaluation_config={"source": ""},
                output_type="boolean",
                output_config={},
                enabled=True,
                created_by=self.user,
                conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
            )

    def test_hog_evaluation_recompiles_bytecode_on_update(self):
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Hog Eval",
            evaluation_type="hog",
            evaluation_config={"source": "return true"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
        )

        evaluation.refresh_from_db()
        original_bytecode = evaluation.evaluation_config["bytecode"]

        evaluation.evaluation_config = {"source": "return false"}
        evaluation.save()
        evaluation.refresh_from_db()

        self.assertIn("bytecode", evaluation.evaluation_config)
        self.assertNotEqual(evaluation.evaluation_config["bytecode"], original_bytecode)

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


class TestEvaluationStatusCoercion(BaseTest):
    def _create(self, **overrides) -> Evaluation:
        defaults: dict = {
            "team": self.team,
            "name": "Test",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "p"},
            "output_type": "boolean",
            "output_config": {},
            "created_by": self.user,
            "conditions": [],
        }
        defaults.update(overrides)
        return Evaluation.objects.create(**defaults)

    @parameterized.expand(
        [
            (True, EvaluationStatus.ACTIVE),
            (False, EvaluationStatus.PAUSED),
        ]
    )
    def test_new_row_status_derived_from_enabled(self, enabled, expected_status):
        evaluation = self._create(enabled=enabled)
        self.assertEqual(evaluation.status, expected_status)
        self.assertIsNone(evaluation.status_reason)

    def test_flipping_enabled_false_on_active_row_transitions_to_paused(self):
        evaluation = self._create(enabled=True)
        evaluation.enabled = False
        evaluation.save()
        self.assertEqual(evaluation.status, EvaluationStatus.PAUSED)
        self.assertFalse(evaluation.enabled)

    def test_flipping_enabled_true_on_errored_row_transitions_to_active_and_clears_reason(self):
        evaluation = self._create(enabled=False)
        evaluation.status = EvaluationStatus.ERROR
        evaluation.status_reason = EvaluationStatusReason.TRIAL_LIMIT_REACHED
        evaluation.save()
        self.assertEqual(evaluation.status, EvaluationStatus.ERROR)

        evaluation.enabled = True
        evaluation.save()
        self.assertEqual(evaluation.status, EvaluationStatus.ACTIVE)
        self.assertTrue(evaluation.enabled)
        self.assertIsNone(evaluation.status_reason)

    def test_setting_status_error_requires_reason(self):
        evaluation = self._create(enabled=True)
        evaluation.status = EvaluationStatus.ERROR
        with self.assertRaises(ValidationError):
            evaluation.save()

    def test_setting_status_error_with_reason_forces_enabled_false(self):
        evaluation = self._create(enabled=True)
        evaluation.status = EvaluationStatus.ERROR
        evaluation.status_reason = EvaluationStatusReason.MODEL_NOT_ALLOWED
        evaluation.save()
        self.assertEqual(evaluation.status, EvaluationStatus.ERROR)
        self.assertFalse(evaluation.enabled)
        self.assertEqual(evaluation.status_reason, EvaluationStatusReason.MODEL_NOT_ALLOWED)

    def test_paused_status_clears_any_stale_status_reason(self):
        evaluation = self._create(enabled=True)
        evaluation.status = EvaluationStatus.ERROR
        evaluation.status_reason = EvaluationStatusReason.TRIAL_LIMIT_REACHED
        evaluation.save()

        evaluation.status = EvaluationStatus.PAUSED
        evaluation.save()
        self.assertIsNone(evaluation.status_reason)

    def test_set_status_helper_transitions_all_three_fields(self):
        evaluation = self._create(enabled=True)
        evaluation.set_status(EvaluationStatus.ERROR, EvaluationStatusReason.PROVIDER_KEY_DELETED)
        evaluation.refresh_from_db()
        self.assertEqual(evaluation.status, EvaluationStatus.ERROR)
        self.assertEqual(evaluation.status_reason, EvaluationStatusReason.PROVIDER_KEY_DELETED)
        self.assertFalse(evaluation.enabled)

    def test_refresh_from_db_resets_change_tracking_baseline(self):
        """After refresh_from_db, a subsequent edit must be compared against DB state — not the
        pre-refresh in-memory snapshot. Without this, a user toggling enabled=True after refresh on
        an errored instance would be silently coerced back to enabled=False."""
        evaluation = self._create(enabled=True)
        # Simulate a system transition happening elsewhere (another worker, another request, etc.).
        Evaluation.objects.filter(id=evaluation.id).update(
            enabled=False, status=EvaluationStatus.ERROR, status_reason=EvaluationStatusReason.TRIAL_LIMIT_REACHED
        )

        evaluation.refresh_from_db()
        # User re-enables from the now-refreshed state.
        evaluation.enabled = True
        evaluation.save()
        self.assertEqual(evaluation.status, EvaluationStatus.ACTIVE)
        self.assertTrue(evaluation.enabled)
        self.assertIsNone(evaluation.status_reason)
