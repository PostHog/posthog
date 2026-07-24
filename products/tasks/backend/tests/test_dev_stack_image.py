import pytest
from unittest.mock import patch

from products.tasks.backend.logic.services.dev_stack_image import DevStackImageBakeError, bake_dev_stack_image
from products.tasks.backend.logic.services.sandbox import ExecutionResult


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
    def _run(self, exit_code: int):
        fake_cls = _make_fake_sandbox_cls(exit_code)
        with patch("products.tasks.backend.logic.services.sandbox.get_sandbox_class", return_value=fake_cls):
            return fake_cls, bake_dev_stack_image("posthog-dev-stack-test")

    def test_successful_bake_publishes_and_destroys_sandbox(self):
        fake_cls, image_id = self._run(exit_code=0)

        assert image_id == "im-fake-123"
        (sandbox,) = fake_cls.instances
        assert sandbox.published_name == "posthog-dev-stack-test"
        assert sandbox.destroyed is True
        # The bake script actually reaches the sandbox.
        assert any(b"bin/migrate" in payload for payload in sandbox.written_files.values())

    def test_failed_bake_never_publishes_but_still_destroys_sandbox(self):
        # Publishing after a failed bake would overwrite the last good image with a broken
        # one under the same name — every internal VM run would then boot from it.
        fake_cls = _make_fake_sandbox_cls(exit_code=1)
        with patch("products.tasks.backend.logic.services.sandbox.get_sandbox_class", return_value=fake_cls):
            with pytest.raises(DevStackImageBakeError):
                bake_dev_stack_image("posthog-dev-stack-test")

        (sandbox,) = fake_cls.instances
        assert sandbox.published_name is None
        assert sandbox.destroyed is True
