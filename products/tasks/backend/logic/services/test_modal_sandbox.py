import pytest
from unittest.mock import MagicMock

from products.tasks.backend.constants import DEFAULT_SANDBOX_WORKING_DIR, SNAPSHOT_KIND_DIRECTORY
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


class TestModalSandboxDirectorySnapshotMount:
    @pytest.mark.parametrize(
        "mount_path, expect_mounted",
        [
            (DEFAULT_SANDBOX_WORKING_DIR, True),
            # Legacy captures of the system temp dir: re-mounting replaces the live /tmp and
            # kills Modal's in-sandbox helpers — must never reach mount_image again.
            ("/tmp", False),
            # Upstream validation strips a disallowed path; the missing path must not be
            # re-defaulted into a mount of mismatched content.
            (None, False),
        ],
    )
    def test_directory_snapshot_mount_guard(self, patched_modal, mocker, mount_path, expect_mounted):
        snapshot_image = MagicMock()
        mocker.patch("modal.Image.from_id", return_value=snapshot_image)
        fake_sandbox = patched_modal.return_value

        sandbox = ModalSandbox.create(
            SandboxConfig(
                name="test",
                template=SandboxTemplate.DEFAULT_BASE,
                snapshot_external_id="im-dir",
                snapshot_kind=SNAPSHOT_KIND_DIRECTORY,
                snapshot_mount_path=mount_path,
            )
        )

        if expect_mounted:
            fake_sandbox.mount_image.assert_called_once_with(mount_path, snapshot_image)
            assert sandbox.config.snapshot_restored is True
        else:
            fake_sandbox.mount_image.assert_not_called()
            assert sandbox.config.snapshot_restored is False
