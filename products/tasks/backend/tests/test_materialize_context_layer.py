from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from asgiref.sync import async_to_sync

from products.context_layer.backend.facade.api import ContextLayerMount
from products.tasks.backend.logic.services.sandbox import ExecutionResult
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

    def test_pushes_the_bundle_into_the_sandbox_so_the_mount_needs_no_storage_egress(self) -> None:
        sandbox = MagicMock()
        sandbox.write_file.return_value = ExecutionResult(stdout="", stderr="", exit_code=0, error=None)
        sandbox.execute.return_value = ExecutionResult(stdout="", stderr="", exit_code=0, error=None)
        mount = ContextLayerMount(bundle=b"# v2 git bundle\n", head_sha="a" * 40)
        with (
            patch(f"{MODULE}.context_layer_facade.get_sandbox_mount", return_value=mount),
            patch(
                "products.tasks.backend.logic.services.sandbox.get_sandbox_class",
                return_value=MagicMock(get_by_id=MagicMock(return_value=sandbox)),
            ),
        ):
            output = async_to_sync(materialize_context_layer_in_sandbox)(
                MaterializeContextLayerInput(context=_context(), sandbox_id="sandbox-1")
            )

        assert output.mounted is True
        assert sandbox.write_file.call_args.args == ("/tmp/workspace/context.bundle", mount.bundle)
        command = sandbox.execute.call_args.args[0]
        assert "curl" not in command
        assert "git clone --quiet /tmp/workspace/context.bundle /tmp/workspace/context" in command
