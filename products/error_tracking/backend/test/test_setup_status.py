from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest, _create_event, flush_persons_and_events

from langchain_core.runnables import RunnableConfig

from posthog.models import RemoteConfig, Team

from products.error_tracking.backend.max_tools import GetErrorTrackingSetupStatusTool

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.utils.types import AssistantState


class TestGetErrorTrackingSetupStatusTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.team.autocapture_exceptions_opt_in = True
        Team.objects.filter(id=self.team.id).update(autocapture_exceptions_opt_in=True)
        RemoteConfig.objects.update_or_create(
            team=self.team,
            defaults={"config": {"autocaptureExceptions": True}},
        )

        _create_event(
            event="account_created",
            distinct_id="node-user",
            team=self.team,
            properties={"$lib": "posthog-node", "$lib_version": "5.48.1"},
        )
        flush_persons_and_events()

    async def test_warns_when_node_sdk_needs_local_exception_autocapture(self) -> None:
        config = RunnableConfig()
        tool = await GetErrorTrackingSetupStatusTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=config,
            context_manager=AssistantContextManager(team=self.team, user=self.user, config=config),
        )

        content, artifact = await tool._arun_impl()

        assert "Project exception autocapture setting: enabled" in content
        assert "Published remote config: enabled" in content
        assert "No exception events were received in the last 7 days" in content
        assert "posthog-node requires `enableExceptionAutocapture: true`" in content
        assert "PostHog cannot verify this local SDK option" in content
        assert artifact == {
            "project_autocapture_enabled": True,
            "remote_config_autocapture_enabled": True,
            "has_issues": False,
            "recent_data_available": True,
            "recent_period_days": 7,
            "recent_event_count": 1,
            "recent_exception_count": 0,
            "observed_sdks": [
                {
                    "library": "posthog-node",
                    "event_count": 1,
                    "autocapture_configuration": "local",
                    "local_option": "enableExceptionAutocapture",
                }
            ],
            "warnings": [
                {
                    "code": "node_autocapture_requires_local_configuration",
                    "message": (
                        "posthog-node requires `enableExceptionAutocapture: true` in the SDK initialization. "
                        "The project setting does not enable exception autocapture for posthog-node. "
                        "PostHog cannot verify this local SDK option from event data."
                    ),
                }
            ],
        }
