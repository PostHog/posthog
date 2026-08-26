import shutil
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.constants import (
    DEFAULT_SANDBOX_WORKING_DIR,
    SNAPSHOT_KIND_DIRECTORY,
    SNAPSHOT_KIND_FILESYSTEM,
)
from products.tasks.backend.logic.services.modal_sandbox import (
    DEFAULT_MODAL_APP_NAME,
    LOCAL_MODAL_AGENT_SHADOW_DIR,
    LOCAL_MODAL_NOTEBOOK_KERNEL_DIR,
    LOCAL_MODAL_NOTEBOOK_KERNEL_MODULE,
    NOTEBOOK_MODAL_APP_NAME,
    SELF_DRIVING_MODAL_APP_NAME,
    STREAMLIT_MODAL_APP_NAME,
    ModalSandbox,
    _prepare_local_modal_build_context,
)
from products.tasks.backend.logic.services.sandbox import (
    SELF_DRIVING_ORIGIN_PRODUCTS,
    SandboxConfig,
    SandboxStatus,
    SandboxTemplate,
    SandboxWorkload,
    get_sandbox_class_for_backend,
    workload_for_origin_product,
)
from products.tasks.backend.models import Task


def test_destroy_updates_status_before_modal_termination_settles(mocker):
    handle = MagicMock(object_id="sb-test")
    handle.poll.return_value = None
    mocker.patch.object(ModalSandbox, "_get_app_for_config", return_value=MagicMock())
    sandbox = ModalSandbox(handle, SandboxConfig(name="test"))

    sandbox.destroy()

    assert sandbox.get_status() == SandboxStatus.SHUTDOWN
    handle.terminate.assert_called_once_with()


@pytest.fixture
def patched_modal(mocker):
    fake_sandbox = MagicMock()
    fake_sandbox.object_id = "sb-test"

    mocker.patch.object(ModalSandbox, "_get_app_for_config", return_value=MagicMock())
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
        fake_sandbox.exec.return_value.poll.return_value = 0

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

    @pytest.mark.parametrize("snapshot_kind", [SNAPSHOT_KIND_DIRECTORY, SNAPSHOT_KIND_FILESYSTEM])
    def test_wedged_restore_falls_back_to_base_image(self, patched_modal, mocker, snapshot_kind):
        snapshot_image = MagicMock()
        mocker.patch("modal.Image.from_id", return_value=snapshot_image)
        wedged = MagicMock()
        wedged.object_id = "sb-wedged"
        wedged.exec.return_value.poll.return_value = 137
        fresh = MagicMock()
        fresh.object_id = "sb-fresh"
        patched_modal.side_effect = [wedged, fresh]

        sandbox = ModalSandbox.create(
            SandboxConfig(
                name="test",
                template=SandboxTemplate.DEFAULT_BASE,
                snapshot_external_id="im-snap",
                snapshot_kind=snapshot_kind,
                snapshot_mount_path=DEFAULT_SANDBOX_WORKING_DIR if snapshot_kind == SNAPSHOT_KIND_DIRECTORY else None,
            )
        )

        if snapshot_kind == SNAPSHOT_KIND_DIRECTORY:
            wedged.mount_image.assert_called_once_with(DEFAULT_SANDBOX_WORKING_DIR, snapshot_image)
        else:
            wedged.mount_image.assert_not_called()
        wedged.terminate.assert_called_once()
        assert sandbox.id == "sb-fresh"
        assert sandbox.config.snapshot_restored is False


class TestModalSandboxAppRouting:
    PRODUCTION_APP_NAMES = frozenset(
        {
            DEFAULT_MODAL_APP_NAME,
            NOTEBOOK_MODAL_APP_NAME,
            STREAMLIT_MODAL_APP_NAME,
            SELF_DRIVING_MODAL_APP_NAME,
        }
    )

    @pytest.fixture
    def app_lookup(self, mocker):
        return mocker.patch("modal.App.lookup", return_value=MagicMock())

    @pytest.mark.parametrize(
        "template, workload, expected_app",
        [
            (SandboxTemplate.DEFAULT_BASE, SandboxWorkload.DEFAULT, DEFAULT_MODAL_APP_NAME),
            (SandboxTemplate.DEFAULT_BASE, SandboxWorkload.SELF_DRIVING, SELF_DRIVING_MODAL_APP_NAME),
            # Self-driving runs on the VM runtime stay in the self-driving app.
            (SandboxTemplate.VM_BASE, SandboxWorkload.SELF_DRIVING, SELF_DRIVING_MODAL_APP_NAME),
            # Product templates own their app regardless of workload.
            (SandboxTemplate.NOTEBOOK_BASE, SandboxWorkload.SELF_DRIVING, NOTEBOOK_MODAL_APP_NAME),
            (SandboxTemplate.STREAMLIT_BASE, SandboxWorkload.SELF_DRIVING, STREAMLIT_MODAL_APP_NAME),
        ],
    )
    def test_app_resolution(self, app_lookup, template, workload, expected_app):
        ModalSandbox._get_app_for_config(SandboxConfig(name="test", template=template, workload=workload))

        app_lookup.assert_called_once_with(expected_app, create_if_missing=True)

    def test_created_sandbox_is_booked_against_the_workload_app(self, mocker, app_lookup):
        mocker.patch(
            "products.tasks.backend.logic.services.modal_sandbox._get_template_image",
            return_value=MagicMock(),
        )
        create = mocker.patch("modal.Sandbox.create", return_value=MagicMock(object_id="sb-test"))

        ModalSandbox.create(SandboxConfig(name="test", workload=SandboxWorkload.SELF_DRIVING))

        app_lookup.assert_any_call(SELF_DRIVING_MODAL_APP_NAME, create_if_missing=True)
        assert create.call_args.kwargs["app"] is app_lookup.return_value

    @pytest.mark.parametrize("backend", ["modal_docker", "modal_evals"])
    @pytest.mark.parametrize(
        "template",
        [
            SandboxTemplate.DEFAULT_BASE,
            SandboxTemplate.VM_BASE,
            SandboxTemplate.NOTEBOOK_BASE,
            SandboxTemplate.STREAMLIT_BASE,
        ],
    )
    @pytest.mark.parametrize("workload", [SandboxWorkload.DEFAULT, SandboxWorkload.SELF_DRIVING])
    def test_local_and_eval_providers_never_resolve_a_production_app(self, app_lookup, backend, template, workload):
        # Every app name has to be a class attribute for the provider subclasses to shadow it.
        # A module constant read directly would leak local and eval boxes into a production app.
        sandbox_cls = get_sandbox_class_for_backend(backend)
        assert issubclass(sandbox_cls, ModalSandbox)

        sandbox_cls._get_app_for_config(SandboxConfig(name="test", template=template, workload=workload))

        assert app_lookup.call_args.args[0] not in self.PRODUCTION_APP_NAMES


class TestSelfDrivingWorkloadMapping:
    @pytest.mark.parametrize(
        "origin_product, expected",
        [
            (Task.OriginProduct.SIGNAL_REPORT, SandboxWorkload.SELF_DRIVING),
            (Task.OriginProduct.SIGNALS_SCOUT, SandboxWorkload.SELF_DRIVING),
            (Task.OriginProduct.REVIEW_HOG, SandboxWorkload.SELF_DRIVING),
            (Task.OriginProduct.USER_CREATED, SandboxWorkload.DEFAULT),
            (Task.OriginProduct.SLACK, SandboxWorkload.DEFAULT),
            (Task.OriginProduct.LOOP, SandboxWorkload.DEFAULT),
            (None, SandboxWorkload.DEFAULT),
        ],
    )
    def test_workload_for_origin_product(self, origin_product, expected):
        value = origin_product.value if origin_product is not None else None

        assert workload_for_origin_product(value) == expected

    def test_every_self_driving_origin_is_a_real_origin_product(self):
        # The set is held as strings to keep the sandbox layer model-free, so a renamed or
        # removed OriginProduct would otherwise silently drop that product out of the fleet.
        assert SELF_DRIVING_ORIGIN_PRODUCTS <= {choice.value for choice in Task.OriginProduct}


class TestLocalModalBuildContext:
    def test_base_context_carries_the_agent_shadow_sources(self):
        # The base Dockerfile's first stage COPYs and builds the agent-shadow observer, so the
        # trimmed DEBUG context must carry its sources or every local sandbox fails at image build.
        _prepare_local_modal_build_context.cache_clear()
        with (
            patch("products.tasks.backend.logic.services.modal_sandbox.LocalSkillsCache"),
            patch("products.tasks.backend.logic.services.modal_sandbox.populate_skills_directory"),
        ):
            _dockerfile_path, context_dir = _prepare_local_modal_build_context(SandboxTemplate.DEFAULT_BASE)
        try:
            root = Path(context_dir)
            assert (root / LOCAL_MODAL_AGENT_SHADOW_DIR / "go.mod").is_file()
            assert (root / LOCAL_MODAL_AGENT_SHADOW_DIR / "main.go").is_file()
        finally:
            shutil.rmtree(context_dir, ignore_errors=True)
            _prepare_local_modal_build_context.cache_clear()

    def test_notebook_context_carries_the_baked_kernel_package(self):
        # DEBUG builds the notebook image from this trimmed context, not the repo root, so a
        # Dockerfile COPY whose source is missing here fails the build and no notebook
        # sandbox starts. The registry path in production never exercises it.
        _prepare_local_modal_build_context.cache_clear()
        _dockerfile_path, context_dir = _prepare_local_modal_build_context(SandboxTemplate.NOTEBOOK_BASE)
        try:
            root = Path(context_dir)
            assert (root / LOCAL_MODAL_NOTEBOOK_KERNEL_MODULE).is_file()
            assert (root / LOCAL_MODAL_NOTEBOOK_KERNEL_DIR / "server.py").is_file()
            assert not (root / LOCAL_MODAL_NOTEBOOK_KERNEL_DIR / "__pycache__").exists()
        finally:
            shutil.rmtree(context_dir, ignore_errors=True)
            _prepare_local_modal_build_context.cache_clear()
