import uuid

import pytest
from unittest.mock import patch

from products.tasks.backend.logic.services.dev_stack_image import (
    DevStackImageBakeError,
    bake_dev_stack_image,
    refresh_dev_stack_image_if_base_changed,
)
from products.tasks.backend.logic.services.sandbox import ExecutionResult

BASE_REFERENCE = "ghcr.io/posthog/posthog-sandbox-vm@sha256:current"


def _unique_publish_name() -> str:
    # The baked-reference and claim stamps live in a shared cache; a unique image name
    # per test keeps tests order-independent.
    return f"posthog-dev-stack-test-{uuid.uuid4().hex[:8]}"


class _FakeStream:
    def __init__(self, exit_code: int):
        self._exit_code = exit_code

    def iter_stdout(self):
        yield "[bake] starting dockerd\n"
        yield "[bake] running migrations\n"

    def wait(self) -> ExecutionResult:
        return ExecutionResult(stdout="", stderr="", exit_code=self._exit_code, error=None)


def _make_fake_sandbox_cls(exit_code: int):
    from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox

    class FakeSandbox(ModalSandbox):
        instances: list["FakeSandbox"] = []

        def __init__(self):  # skip ModalSandbox.__init__ — no real Modal objects in tests
            self.id = "sb-fake"
            self.destroyed = False
            self.published_name: str | None = None
            self.written_files: dict[str, bytes] = {}
            FakeSandbox.instances.append(self)

        @classmethod
        def create(cls, config):
            return cls()

        def write_file(self, path: str, payload: bytes) -> ExecutionResult:
            self.written_files[path] = payload
            return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

        def execute_stream(self, command: str, timeout_seconds: int | None = None) -> _FakeStream:
            return _FakeStream(exit_code)

        def publish_filesystem_image(self, publish_name: str) -> str:
            self.published_name = publish_name
            return "im-fake-123"

        def destroy(self) -> None:
            self.destroyed = True

    return FakeSandbox


class TestBakeDevStackImage:
    def test_successful_bake_publishes_destroys_sandbox_and_settles_refresh(self):
        publish_name = _unique_publish_name()
        fake_cls = _make_fake_sandbox_cls(exit_code=0)
        with (
            patch("products.tasks.backend.logic.services.dev_stack_image.get_sandbox_class", return_value=fake_cls),
            patch(
                "products.tasks.backend.logic.services.modal_sandbox.resolve_template_base_image_reference",
                return_value=BASE_REFERENCE,
            ),
        ):
            image_id = bake_dev_stack_image(publish_name)

        assert image_id == "im-fake-123"
        (sandbox,) = fake_cls.instances
        assert sandbox.published_name == publish_name
        assert sandbox.destroyed is True
        # The bake script actually reaches the sandbox.
        assert any(b"bin/migrate" in payload for payload in sandbox.written_files.values())

        # A successful bake records the base reference it used, so the refresh sweep
        # stops dispatching until the base digest actually moves.
        with (
            patch(
                "products.tasks.backend.logic.services.dev_stack_image.is_dev_stack_image_bake_enabled",
                return_value=True,
            ),
            patch(
                "products.tasks.backend.logic.services.modal_sandbox.resolve_template_base_image_reference",
                return_value=BASE_REFERENCE,
            ),
            patch("products.tasks.backend.temporal.client.execute_bake_dev_stack_image_workflow") as dispatch_mock,
        ):
            assert refresh_dev_stack_image_if_base_changed(publish_name) is False
        dispatch_mock.assert_not_called()

    def test_failed_bake_never_publishes_but_still_destroys_sandbox(self):
        # Publishing after a failed bake would overwrite the last good image with a broken
        # one under the same name — every internal VM run would then boot from it.
        fake_cls = _make_fake_sandbox_cls(exit_code=1)
        with patch("products.tasks.backend.logic.services.dev_stack_image.get_sandbox_class", return_value=fake_cls):
            with pytest.raises(DevStackImageBakeError):
                bake_dev_stack_image(_unique_publish_name())

        (sandbox,) = fake_cls.instances
        assert sandbox.published_name is None
        assert sandbox.destroyed is True


class TestRefreshDevStackImageIfBaseChanged:
    def _refresh(self, publish_name: str, *, flag_enabled: bool = True, base_reference: str | None = BASE_REFERENCE):
        with (
            patch(
                "products.tasks.backend.logic.services.dev_stack_image.is_dev_stack_image_bake_enabled",
                return_value=flag_enabled,
            ),
            patch(
                "products.tasks.backend.logic.services.modal_sandbox.resolve_template_base_image_reference",
                return_value=base_reference,
            ),
            patch("products.tasks.backend.temporal.client.execute_bake_dev_stack_image_workflow") as dispatch_mock,
        ):
            dispatched = refresh_dev_stack_image_if_base_changed(publish_name)
        return dispatched, dispatch_mock

    def test_dispatches_at_most_once_per_new_base_digest(self):
        # The 10-minute sweep must not redispatch while a rebake for the same digest is
        # in flight or has failed — that would start a paid Modal bake on every tick.
        publish_name = _unique_publish_name()

        dispatched, dispatch_mock = self._refresh(publish_name)
        assert dispatched is True
        dispatch_mock.assert_called_once_with(publish_name)

        dispatched, dispatch_mock = self._refresh(publish_name)
        assert dispatched is False
        dispatch_mock.assert_not_called()

    @pytest.mark.parametrize("flag_enabled, base_reference", [(False, BASE_REFERENCE), (True, None)])
    def test_skips_when_flag_off_or_no_registry_reference(self, flag_enabled, base_reference):
        dispatched, dispatch_mock = self._refresh(
            _unique_publish_name(), flag_enabled=flag_enabled, base_reference=base_reference
        )
        assert dispatched is False
        dispatch_mock.assert_not_called()
