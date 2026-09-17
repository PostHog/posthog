from unittest import TestCase
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import AgentMode

from ..user_interview import (
    ReadOnlyUserInterviewAgentToolkit,
    UserInterviewAgentToolkit,
    chat_agent_plan_user_interview_agent,
    subagent_user_interview_agent,
    user_interview_agent,
)


def _make_toolkit(toolkit_class):
    # The `tools` property only imports and returns classes — it never touches `_team`,
    # `_user`, or `_context_manager`, so mocks are sufficient and keep the test DB-free.
    return toolkit_class(team=MagicMock(), user=MagicMock(), context_manager=MagicMock())


class TestUserInterviewAgentToolkit(TestCase):
    def test_toolkit_includes_both_user_interview_tools(self):
        tool_class_names = [tool_class.__name__ for tool_class in _make_toolkit(UserInterviewAgentToolkit).tools]

        self.assertIn("CreateUserInterviewTopicTool", tool_class_names)
        self.assertIn("AnalyzeUserInterviewsTool", tool_class_names)

    def test_read_only_toolkit_excludes_create_tool(self):
        tool_class_names = [
            tool_class.__name__ for tool_class in _make_toolkit(ReadOnlyUserInterviewAgentToolkit).tools
        ]

        self.assertEqual(tool_class_names, ["AnalyzeUserInterviewsTool"])

    def test_toolkit_has_trajectory_examples(self):
        examples = UserInterviewAgentToolkit.POSITIVE_TODO_EXAMPLES
        self.assertIsNotNone(examples)
        self.assertGreater(len(examples), 0)

    @parameterized.expand(
        [
            ("user_interview_agent", user_interview_agent),
            ("subagent_user_interview_agent", subagent_user_interview_agent),
            ("chat_agent_plan_user_interview_agent", chat_agent_plan_user_interview_agent),
        ]
    )
    def test_mode_definition_uses_user_interview_mode(self, _name, definition):
        self.assertEqual(definition.mode, AgentMode.USER_INTERVIEW)

    @parameterized.expand(
        [
            ("subagent_user_interview_agent", subagent_user_interview_agent),
            ("chat_agent_plan_user_interview_agent", chat_agent_plan_user_interview_agent),
        ]
    )
    def test_read_only_variants_use_read_only_toolkit(self, _name, definition):
        self.assertEqual(definition.toolkit_class, ReadOnlyUserInterviewAgentToolkit)
