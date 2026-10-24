from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.logic.services.sandbox import AgentServerResult
from products.tasks.backend.logic.services.sandbox_housekeeping import SandboxHousekeeping
from products.tasks.backend.temporal.process_task import sandbox_connection

HOUSEKEEPING_AT = datetime(2026, 10, 21, tzinfo=UTC)
MEASURED_AT = datetime(2026, 10, 22, tzinfo=UTC)


def _housekeeping(cpu_usage_usec: int | None) -> SandboxHousekeeping:
    return SandboxHousekeeping(
        agent_version=None,
        cpu_billing_sampler_started=cpu_usage_usec is not None,
        cpu_usage_usec=cpu_usage_usec,
        billed_cpu_usage_usec=500 if cpu_usage_usec is not None else None,
        cpu_usage_measured_at=HOUSEKEEPING_AT if cpu_usage_usec is not None else None,
    )


@pytest.mark.parametrize(
    ("housekeeping", "expected"),
    [
        (_housekeeping(1_000), (1_000, 500, HOUSEKEEPING_AT)),
        (_housekeeping(None), (2_000, 700, MEASURED_AT)),
        (None, (2_000, 700, MEASURED_AT)),
    ],
)
def test_persist_sandbox_connection_measures_cpu_when_housekeeping_has_none(
    housekeeping: SandboxHousekeeping | None, expected: tuple[int, int, datetime]
) -> None:
    sandbox = MagicMock(id="sandbox-id")

    with (
        patch.object(sandbox_connection, "get_primary_sandbox_jwt_kid", return_value="kid"),
        patch.object(sandbox_connection.TaskRun, "update_state_atomic"),
        patch.object(sandbox_connection, "measure_sandbox_cpu_usage", return_value=(2_000, MEASURED_AT)),
        patch.object(sandbox_connection, "measure_sandbox_billed_cpu_usage", return_value=700),
        patch.object(sandbox_connection, "open_sandbox_session") as open_session,
    ):
        sandbox_connection.persist_sandbox_connection(
            run_id="run-id",
            sandbox=sandbox,
            credentials=AgentServerResult(url="https://sandbox.example", token=None),
            sandbox_created_at=None,
            task_runtime=None,
            housekeeping=housekeeping,
        )

    kwargs = open_session.call_args.kwargs
    assert (
        kwargs["cpu_usage_attribution_usec"],
        kwargs["billed_cpu_usage_attribution_usec"],
        kwargs["cpu_usage_attribution_measured_at"],
    ) == expected
