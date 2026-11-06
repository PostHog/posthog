from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from asgiref.sync import async_to_sync

from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.materialize_context_layer import (
    MaterializeContextLayerInput,
    materialize_context_layer_in_sandbox,
)

MODULE = "products.tasks.backend.temporal.process_task.activities.materialize_context_layer"


def _context() -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-1",
        run_id="run-1",
        team_id=1,
        team_uuid="00000000-0000-0000-0000-000000000001",
        organization_id="00000000-0000-0000-0000-000000000002",
        github_integration_id=None,
        repository=None,
        distinct_id="user-1",
    )


class TestMaterializeContextLayer(SimpleTestCase):
    def test_clears_a_leftover_checkout_when_the_org_has_no_wiki_to_mount(self) -> None:
        # A directory-resumed sandbox restores the previous run's checkout, so a
        # wiki that has gone dark stays readable unless the mount removes it.
        sandbox = MagicMock()
        with (
            patch(f"{MODULE}.context_layer_facade.get_sandbox_mount", return_value=None),
            patch(
                "products.tasks.backend.logic.services.sandbox.get_sandbox_class",
                return_value=MagicMock(get_by_id=MagicMock(return_value=sandbox)),
            ),
        ):
            output = async_to_sync(materialize_context_layer_in_sandbox)(
                MaterializeContextLayerInput(context=_context(), sandbox_id="sandbox-1")
            )

        assert output.mounted is False
        command = sandbox.execute.call_args.args[0]
        assert command.startswith("rm -rf ")
        assert "/tmp/workspace/context" in command
