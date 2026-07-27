import pytest

from products.tasks.backend.logic.services.sandbox_config import (
    MAX_SANDBOX_CPU_CORES,
    MAX_SANDBOX_MEMORY_GB,
    MAX_SANDBOX_TTL_SECONDS,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext


def _context(state: dict | None) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="org-id",
        github_integration_id=123,
        repository="explore-science/paper-wizard-frontend",
        distinct_id="distinct",
        state=state,
    )


class TestSandboxResourceOverrides:
    def test_no_state_returns_empty(self):
        assert _context(None).sandbox_resource_overrides() == {}

    def test_valid_values_pass_through(self):
        # ttl stays under MAX_SANDBOX_TTL_SECONDS (== the default TTL, 15min under test).
        overrides = _context(
            {"sandbox_cpu_cores": 2, "sandbox_memory_gb": 8, "sandbox_ttl_seconds": 600}
        ).sandbox_resource_overrides()
        assert overrides == {"cpu_cores": 2.0, "memory_gb": 8.0, "ttl_seconds": 600}

    def test_values_are_clamped_to_max(self):
        overrides = _context(
            {"sandbox_cpu_cores": 999, "sandbox_memory_gb": 9999, "sandbox_ttl_seconds": MAX_SANDBOX_TTL_SECONDS * 10}
        ).sandbox_resource_overrides()
        assert overrides == {
            "cpu_cores": float(MAX_SANDBOX_CPU_CORES),
            "memory_gb": float(MAX_SANDBOX_MEMORY_GB),
            "ttl_seconds": MAX_SANDBOX_TTL_SECONDS,
        }

    @pytest.mark.parametrize("value", [0, -1, True, False, "nope", None])
    def test_invalid_values_are_ignored(self, value):
        state = {"sandbox_cpu_cores": value, "sandbox_memory_gb": value, "sandbox_ttl_seconds": value}
        assert _context(state).sandbox_resource_overrides() == {}
