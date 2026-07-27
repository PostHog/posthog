from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext


def _context(state: dict | None) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="org-id",
        github_integration_id=123,
        repository="posthog/posthog",
        distinct_id="distinct",
        state=state,
    )


class TestToLogContextIsWizardRun:
    def test_normal_run_is_not_a_wizard_run(self):
        assert _context({"run_source": "manual"}).to_log_context()["is_wizard_run"] is False

    def test_missing_state_is_not_a_wizard_run(self):
        assert _context(None).to_log_context()["is_wizard_run"] is False

    def test_empty_wizard_config_still_marks_a_wizard_run(self):
        # `create_wizard_cloud_run` stamps `wizard_config={}` — the key's presence is the
        # marker, so an empty dict must not read as "not a wizard run".
        assert _context({"wizard_config": {}}).to_log_context()["is_wizard_run"] is True

    def test_populated_wizard_config_marks_a_wizard_run(self):
        assert _context({"wizard_config": {"foo": "bar"}}).to_log_context()["is_wizard_run"] is True
