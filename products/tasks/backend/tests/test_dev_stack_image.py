import uuid

import pytest
from unittest.mock import patch

from products.tasks.backend.exceptions import SnapshotTimeoutError
from products.tasks.backend.logic.services.dev_stack_image import (
    PUBLISH_SNAPSHOT_MAX_ATTEMPTS,
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


def _make_fake_sandbox_cls(exit_code: int, publish_failures: int = 0):
    from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox

    class FakeSandbox(ModalSandbox):
        instances: list["FakeSandbox"] = []

        def __init__(self):  # skip ModalSandbox.__init__ — no real Modal objects in tests
            self.id = "sb-fake"
            self.destroyed = False
            self.published_name: str | None = None
            self.publish_attempts = 0
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
            self.publish_attempts += 1
            if self.publish_attempts <= publish_failures:
                raise SnapshotTimeoutError(
                    "Transient error creating snapshot",
                    {"sandbox_id": self.id},
                    cause=RuntimeError("Deadline exceeded"),
                    capture=False,
                )
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

    def test_transient_snapshot_failure_retries_publish_without_rebaking(self):
        # A snapshot timeout after a completed bake must retry on the still-running
        # sandbox — failing the activity instead re-runs the whole 15-25 minute bake.
        publish_name = _unique_publish_name()
        fake_cls = _make_fake_sandbox_cls(exit_code=0, publish_failures=PUBLISH_SNAPSHOT_MAX_ATTEMPTS - 1)
        with (
            patch("products.tasks.backend.logic.services.dev_stack_image.get_sandbox_class", return_value=fake_cls),
            patch(
                "products.tasks.backend.logic.services.modal_sandbox.resolve_template_base_image_reference",
                return_value=BASE_REFERENCE,
            ),
        ):
            image_id = bake_dev_stack_image(publish_name)

        assert image_id == "im-fake-123"
        (sandbox,) = fake_cls.instances  # a single sandbox: the bake itself never re-ran
        assert sandbox.publish_attempts == PUBLISH_SNAPSHOT_MAX_ATTEMPTS
        assert sandbox.published_name == publish_name

    def test_records_base_reference_from_bake_start_when_digest_moves_mid_bake(self):
        # The VM base can be republished during the long bake. The sweep must compare
        # against the digest the bake actually layered on — recording the post-bake
        # digest would make the stale publish look current and never rebake it.
        publish_name = _unique_publish_name()
        current = {"ref": "ghcr.io/posthog/posthog-sandbox-vm@sha256:at-bake-start"}
        fake_cls = _make_fake_sandbox_cls(exit_code=0)

        class MovingBaseSandbox(fake_cls):  # type: ignore[valid-type, misc]
            def publish_filesystem_image(self, publish_name: str) -> str:
                current["ref"] = "ghcr.io/posthog/posthog-sandbox-vm@sha256:moved-mid-bake"
                return super().publish_filesystem_image(publish_name)

        with (
            patch(
                "products.tasks.backend.logic.services.dev_stack_image.get_sandbox_class",
                return_value=MovingBaseSandbox,
            ),
            patch(
                "products.tasks.backend.logic.services.modal_sandbox.resolve_template_base_image_reference",
                side_effect=lambda template: current["ref"],
            ),
        ):
            bake_dev_stack_image(publish_name)

            with (
                patch(
                    "products.tasks.backend.logic.services.dev_stack_image.is_dev_stack_image_bake_enabled",
                    return_value=True,
                ),
                patch("products.tasks.backend.temporal.client.execute_bake_dev_stack_image_workflow") as dispatch_mock,
            ):
                assert refresh_dev_stack_image_if_base_changed(publish_name) is True
            dispatch_mock.assert_called_once_with(publish_name)

    def test_publish_gives_up_after_exhausting_snapshot_attempts(self):
        fake_cls = _make_fake_sandbox_cls(exit_code=0, publish_failures=PUBLISH_SNAPSHOT_MAX_ATTEMPTS)
        with patch("products.tasks.backend.logic.services.dev_stack_image.get_sandbox_class", return_value=fake_cls):
            with pytest.raises(SnapshotTimeoutError):
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

    def test_releases_claim_when_dispatch_fails_so_next_sweep_retries(self):
        # A transient Temporal error must not consume the per-digest claim — that would
        # silently block the fast refresh lane for the claim's whole 7-day TTL.
        publish_name = _unique_publish_name()
        with (
            patch(
                "products.tasks.backend.logic.services.dev_stack_image.is_dev_stack_image_bake_enabled",
                return_value=True,
            ),
            patch(
                "products.tasks.backend.logic.services.modal_sandbox.resolve_template_base_image_reference",
                return_value=BASE_REFERENCE,
            ),
            patch(
                "products.tasks.backend.temporal.client.execute_bake_dev_stack_image_workflow",
                side_effect=RuntimeError("temporal unavailable"),
            ),
            patch("products.tasks.backend.logic.services.dev_stack_image.observe_dev_stack_image_bake") as observe_mock,
        ):
            with pytest.raises(RuntimeError):
                refresh_dev_stack_image_if_base_changed(publish_name)

        observe_mock.assert_called_once_with("dispatch_failed")
        dispatched, dispatch_mock = self._refresh(publish_name)
        assert dispatched is True
        dispatch_mock.assert_called_once_with(publish_name)


class TestBakeDevStackImageTask:
    def test_dispatch_failure_is_counted_and_reraised(self):
        # A Temporal-unreachable night must be distinguishable from the flag being off
        # in the bake metric, while the Celery task still records the failure.
        from products.tasks.backend.facade.tasks import bake_dev_stack_image_task

        with (
            patch("products.tasks.backend.feature_flags.is_dev_stack_image_bake_enabled", return_value=True),
            patch(
                "products.tasks.backend.temporal.client.execute_bake_dev_stack_image_workflow",
                side_effect=RuntimeError("temporal unavailable"),
            ),
            patch("products.tasks.backend.metrics.observe_dev_stack_image_bake") as observe_mock,
        ):
            with pytest.raises(RuntimeError):
                bake_dev_stack_image_task()

        observe_mock.assert_called_once_with("dispatch_failed")
