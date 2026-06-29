import pytest
from unittest.mock import MagicMock

from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
from products.tasks.backend.logic.services.sandbox import SandboxConfig, SandboxTemplate


@pytest.fixture
def patched_modal(mocker):
    fake_sandbox = MagicMock()
    fake_sandbox.object_id = "sb-test"

    mocker.patch.object(ModalSandbox, "_get_app_for_template", return_value=MagicMock())
    mocker.patch(
        "products.tasks.backend.logic.services.modal_sandbox._get_template_image",
        return_value=MagicMock(),
    )
    create = mocker.patch("modal.Sandbox.create", return_value=fake_sandbox)
    return create


class TestModalSandboxVmRuntime:
    @pytest.mark.parametrize(
        "template, vm_runtime, expected_experimental_options",
        [
            (SandboxTemplate.DEFAULT_BASE, True, {"vm_runtime": True}),
            (SandboxTemplate.DEFAULT_BASE, False, None),
            # VM_BASE forces vm_runtime even when the flag is explicitly False.
            (SandboxTemplate.VM_BASE, False, {"vm_runtime": True}),
        ],
    )
    def test_vm_runtime_experimental_option(self, patched_modal, template, vm_runtime, expected_experimental_options):
        ModalSandbox.create(SandboxConfig(name="test", template=template, vm_runtime=vm_runtime))

        kwargs = patched_modal.call_args.kwargs
        if expected_experimental_options is None:
            assert "experimental_options" not in kwargs
        else:
            assert kwargs["experimental_options"] == expected_experimental_options
