from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.team import Team

from products.notebooks.backend.models import KernelRuntime
from products.posthog_ai.eval_harness.harness.kernel_sandboxes import release_kernels

RELEASABLE = [
    (KernelRuntime.Status.STARTING,),
    (KernelRuntime.Status.RUNNING,),
    (KernelRuntime.Status.ERROR,),
]
ALREADY_RELEASED = [
    (KernelRuntime.Status.STOPPED,),
    (KernelRuntime.Status.TIMED_OUT,),
    (KernelRuntime.Status.DISCARDED,),
]


class TestReleaseKernels(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.sandbox = MagicMock()
        sandbox_class = MagicMock()
        sandbox_class.get_by_id.return_value = self.sandbox
        self.get_sandbox_class = patch(
            "products.posthog_ai.eval_harness.harness.kernel_sandboxes.get_sandbox_class_for_backend",
            return_value=sandbox_class,
        )
        self.get_sandbox_class.start()
        self.addCleanup(self.get_sandbox_class.stop)

    def _runtime(self, *, status: str, team: Team | None = None, sandbox_id: str = "sbx-1") -> KernelRuntime:
        return KernelRuntime.objects.create(
            team=team or self.team,
            notebook_short_id="aBcD1234",
            status=status,
            backend=KernelRuntime.Backend.DOCKER,
            sandbox_id=sandbox_id,
        )

    @parameterized.expand(RELEASABLE)
    def test_destroys_and_marks_stopped(self, status: str) -> None:
        runtime = self._runtime(status=status)

        assert release_kernels(self.team.id) == 1

        self.sandbox.destroy.assert_called_once()
        runtime.refresh_from_db()
        assert runtime.status == KernelRuntime.Status.STOPPED

    @parameterized.expand(ALREADY_RELEASED)
    def test_leaves_already_released_runtimes_alone(self, status: str) -> None:
        runtime = self._runtime(status=status)

        assert release_kernels(self.team.id) == 0

        self.sandbox.destroy.assert_not_called()
        runtime.refresh_from_db()
        assert runtime.status == status

    def test_retries_a_sandbox_that_could_not_be_destroyed(self) -> None:
        self.sandbox.destroy.side_effect = RuntimeError("provider unreachable")
        runtime = self._runtime(status=KernelRuntime.Status.RUNNING)

        assert release_kernels(self.team.id) == 0

        runtime.refresh_from_db()
        assert runtime.status == KernelRuntime.Status.RUNNING

        self.sandbox.destroy.side_effect = None

        assert release_kernels(self.team.id) == 1

        runtime.refresh_from_db()
        assert runtime.status == KernelRuntime.Status.STOPPED

    def test_scoping_by_team_spares_a_concurrent_case(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other case")
        mine = self._runtime(status=KernelRuntime.Status.RUNNING)
        theirs = self._runtime(status=KernelRuntime.Status.RUNNING, team=other_team, sandbox_id="sbx-2")

        assert release_kernels(self.team.id) == 1

        mine.refresh_from_db()
        theirs.refresh_from_db()
        assert mine.status == KernelRuntime.Status.STOPPED
        assert theirs.status == KernelRuntime.Status.RUNNING

    def test_unscoped_sweep_releases_every_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other case")
        self._runtime(status=KernelRuntime.Status.RUNNING)
        self._runtime(status=KernelRuntime.Status.RUNNING, team=other_team, sandbox_id="sbx-2")

        assert release_kernels() == 2
