from posthog.test.base import BaseTest

from products.signals.backend.temporal.agentic import SIGNALS_REPO_DISCOVERY_ENV_NAME, get_or_create_signals_sandbox_env
from products.tasks.backend.models import SandboxEnvironment


class TestGetOrCreateSignalsSandboxEnv(BaseTest):
    def test_creates_internal_environment(self):
        env_id = get_or_create_signals_sandbox_env(
            self.team.id,
            SIGNALS_REPO_DISCOVERY_ENV_NAME,
            SandboxEnvironment.NetworkAccessLevel.TRUSTED,
        )

        env = SandboxEnvironment.objects.get(id=env_id)
        self.assertTrue(env.internal)
        self.assertFalse(env.private)
        self.assertEqual(env.network_access_level, SandboxEnvironment.NetworkAccessLevel.TRUSTED)

    def test_repeated_calls_produce_a_single_row(self):
        first = get_or_create_signals_sandbox_env(
            self.team.id,
            SIGNALS_REPO_DISCOVERY_ENV_NAME,
            SandboxEnvironment.NetworkAccessLevel.TRUSTED,
        )
        second = get_or_create_signals_sandbox_env(
            self.team.id,
            SIGNALS_REPO_DISCOVERY_ENV_NAME,
            SandboxEnvironment.NetworkAccessLevel.FULL,
        )

        self.assertEqual(first, second)
        self.assertEqual(
            SandboxEnvironment.objects.filter(
                team_id=self.team.id, name=SIGNALS_REPO_DISCOVERY_ENV_NAME, internal=True
            ).count(),
            1,
        )
        # The policy is reasserted on every call.
        env = SandboxEnvironment.objects.get(id=second)
        self.assertEqual(env.network_access_level, SandboxEnvironment.NetworkAccessLevel.FULL)
