from io import StringIO

from posthog.test.base import BaseTest

from posthog.models.feature_flag import FeatureFlag

from products.tasks.backend.management.commands.setup_background_agents import FEATURE_FLAGS_TO_ENABLE, Command


class TestSetupBackgroundAgentsFeatureFlags(BaseTest):
    def _run(self) -> None:
        command = Command()
        command.stdout = StringIO()  # type: ignore[assignment]
        command._setup_feature_flags()

    def test_creates_flags_at_full_rollout(self):
        self._run()

        for key, name in FEATURE_FLAGS_TO_ENABLE:
            flag = FeatureFlag.objects.get(team=self.team, key=key)
            assert flag.name == name
            assert flag.active is True
            assert flag.deleted is False
            assert flag.filters == {"groups": [{"properties": [], "rollout_percentage": 100}]}

    def test_includes_posthog_code_inbox_flag(self):
        keys = {key for key, _ in FEATURE_FLAGS_TO_ENABLE}
        assert "tasks" in keys
        assert "posthog-code-inbox" in keys

    def test_restores_soft_deleted_flag(self):
        key = FEATURE_FLAGS_TO_ENABLE[0][0]
        FeatureFlag.objects_including_soft_deleted.create(
            team=self.team, key=key, name="Legacy", deleted=True, active=False
        )

        self._run()

        flag = FeatureFlag.objects.get(team=self.team, key=key)
        assert flag.deleted is False
        assert flag.active is True

    def test_is_idempotent(self):
        self._run()
        self._run()

        for key, _ in FEATURE_FLAGS_TO_ENABLE:
            assert FeatureFlag.objects.filter(team=self.team, key=key).count() == 1
