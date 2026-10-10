from parameterized import parameterized

from products.slack_app.backend.api import RulesCommand, parse_rules_command
from products.slack_app.backend.models import ChannelWelcomeMode


class TestParseProjectCommand:
    @parameterized.expand(
        [
            (
                "set_plain",
                "project 2",
                RulesCommand(action="project_set", project_team_id=2),
            ),
            (
                "set_with_request",
                "project 2 fix auth",
                RulesCommand(action="project_set", project_team_id=2),
            ),
            (
                "set_uppercase",
                "PROJECT 17",
                RulesCommand(action="project_set", project_team_id=17),
            ),
            (
                "set_mixed_case",
                "Project 5 set up flag",
                RulesCommand(action="project_set", project_team_id=5),
            ),
            (
                "set_leading_bot_mention",
                "<@U123BOT> project 9 do thing",
                RulesCommand(action="project_set", project_team_id=9),
            ),
            (
                "set_trailing_whitespace",
                "project 4 fix auth   ",
                RulesCommand(action="project_set", project_team_id=4),
            ),
            (
                "set_multiline_remaining",
                "project 4 fix the\nlogin bug",
                RulesCommand(action="project_set", project_team_id=4),
            ),
            (
                "set_extra_internal_whitespace",
                "project   12   build feature",
                RulesCommand(action="project_set", project_team_id=12),
            ),
            (
                "set_backticked_id",
                "project `452770`",
                RulesCommand(action="project_set", project_team_id=452770),
            ),
            (
                "set_bold_id",
                "project *452770*",
                RulesCommand(action="project_set", project_team_id=452770),
            ),
            (
                "set_italic_id_with_request",
                "project _19_ fix auth",
                RulesCommand(action="project_set", project_team_id=19),
            ),
            ("show_plain", "project", RulesCommand(action="project_show")),
            ("show_uppercase", "PROJECT", RulesCommand(action="project_show")),
            ("show_trailing_whitespace", "project   ", RulesCommand(action="project_show")),
            ("show_with_bot_mention", "<@U123BOT> project", RulesCommand(action="project_show")),
            (
                "workspace_set_plain",
                "project workspace 3",
                RulesCommand(action="project_set_workspace", project_team_id=3),
            ),
            (
                "workspace_set_uppercase",
                "PROJECT WORKSPACE 8",
                RulesCommand(action="project_set_workspace", project_team_id=8),
            ),
            (
                "workspace_set_with_bot_mention",
                "<@U123BOT> project workspace 11 go",
                RulesCommand(action="project_set_workspace", project_team_id=11),
            ),
            (
                "workspace_set_trailing_text",
                "project workspace 4 fix auth",
                RulesCommand(action="project_set_workspace", project_team_id=4),
            ),
            (
                "workspace_set_extra_whitespace",
                "project   workspace   6",
                RulesCommand(action="project_set_workspace", project_team_id=6),
            ),
            (
                "workspace_set_backticked_id",
                "project workspace `452770`",
                RulesCommand(action="project_set_workspace", project_team_id=452770),
            ),
            (
                "workspace_set_bold_id",
                "project workspace *8*",
                RulesCommand(action="project_set_workspace", project_team_id=8),
            ),
        ]
    )
    def test_recognized(self, _name: str, text: str, expected: RulesCommand) -> None:
        assert parse_rules_command(text) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("whitespace_only", "   "),
            ("just_bot_mention", "<@U123>"),
            ("non_numeric_id", "project abc"),
            ("prefix_word", "projector 2"),
            ("not_at_head", "fix project 2"),
            ("similar_command", "projects 2"),
            ("regular_message", "hey can you set up a feature flag"),
        ]
    )
    def test_not_a_project_command(self, _name: str, text: str) -> None:
        # The unified parser may still recognize other commands (e.g. "rules list");
        # we only assert no `project_*` match comes back.
        result = parse_rules_command(text)
        if result is not None:
            assert result.action not in {"project_show", "project_set", "project_set_workspace"}


class TestParseWelcomeCommand:
    @parameterized.expand(
        [
            ("show", "welcome", RulesCommand(action="welcome_show")),
            ("channel", "welcome channel", RulesCommand(action="welcome_set", welcome_mode=ChannelWelcomeMode.CHANNEL)),
            ("private", "welcome private", RulesCommand(action="welcome_set", welcome_mode=ChannelWelcomeMode.INVITER)),
            ("off_uppercase", "Welcome OFF", RulesCommand(action="welcome_set", welcome_mode=ChannelWelcomeMode.OFF)),
            ("task_mention", "welcome the new hire to the team", None),
            ("unknown_value", "welcome everyone", None),
        ]
    )
    def test_parse(self, _name: str, text: str, expected: RulesCommand | None) -> None:
        assert parse_rules_command(text) == expected
