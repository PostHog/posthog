from posthog.test.base import BaseTest

from asgiref.sync import async_to_sync

from posthog.models.integration import Integration

from products.review_hog.backend.reviewer.sandbox import executor


class TestBindSandboxIdentity(BaseTest):
    def test_bind_fails_fast_without_github_integration(self) -> None:
        # The guard is the only protection against starting a review for a team that can't spawn
        # GitHub sandboxes; without it the run would fail deep in the first sandbox call instead.
        with self.assertRaisesMessage(RuntimeError, f"team {self.team.id}"):
            async_to_sync(executor.bind_sandbox_identity)(team_id=self.team.id, user_id=self.user.id)

    def test_bind_then_context_uses_the_bound_identity(self) -> None:
        Integration.objects.create(team=self.team, kind="github", config={})

        # bind and the read share one coroutine, so the contextvar set is visible to _sandbox_context_for —
        # the same propagation every sandbox call relies on. A team_id/user_id swap would surface here.
        async def _bind_and_read() -> executor.CustomPromptSandboxContext:
            await executor.bind_sandbox_identity(team_id=self.team.id, user_id=self.user.id)
            return executor._sandbox_context_for("acme/app")

        ctx = async_to_sync(_bind_and_read)()
        assert ctx.team_id == self.team.id
        assert ctx.user_id == self.user.id
        assert ctx.repository == "acme/app"
