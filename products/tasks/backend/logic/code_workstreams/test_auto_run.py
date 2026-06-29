from products.tasks.backend.logic.code_workstreams.auto_run import (
    build_auto_run_prompt,
    build_skill_prompt,
    build_workstream_context,
    select_auto_actions,
)


def _action(**overrides) -> dict:
    base = {"id": "fix_ci", "label": "Fix CI", "skillId": "", "prompt": "Fix the CI", "auto": True}
    base.update(overrides)
    return base


class TestSelectAutoActions:
    def test_returns_auto_actions_for_primary_situation(self):
        bindings = {"ci_failing": [_action(), _action(id="other", auto=False)]}
        actions = select_auto_actions(bindings, "ci_failing")
        assert [a["id"] for a in actions] == ["fix_ci"]

    def test_empty_when_primary_situation_is_none(self):
        bindings = {"ci_failing": [_action()]}
        assert select_auto_actions(bindings, None) == []

    def test_empty_when_situation_has_no_auto_actions(self):
        bindings = {"ci_failing": [_action(auto=False), _action(id="x")]}
        # second has no auto key at all
        bindings["ci_failing"][1].pop("auto")
        assert select_auto_actions(bindings, "ci_failing") == []

    def test_only_considers_primary_not_other_situations(self):
        bindings = {"ci_failing": [_action()], "in_review": []}
        # primary is in_review (no auto), even though ci_failing has an auto action
        assert select_auto_actions(bindings, "in_review") == []

    def test_ignores_actions_without_id(self):
        bindings = {"ci_failing": [_action(id="  "), _action(id="real")]}
        actions = select_auto_actions(bindings, "ci_failing")
        assert [a["id"] for a in actions] == ["real"]

    def test_tolerates_non_list_binding(self):
        assert select_auto_actions({"ci_failing": "nope"}, "ci_failing") == []

    def test_auto_must_be_true_not_truthy(self):
        bindings = {"ci_failing": [_action(auto=1), _action(id="real")]}
        actions = select_auto_actions(bindings, "ci_failing")
        assert [a["id"] for a in actions] == ["real"]


class TestBuildSkillPrompt:
    def test_prefixes_skill_command(self):
        assert build_skill_prompt("fix-ci", "do it") == "/fix-ci\n\ndo it"

    def test_no_skill_returns_body(self):
        assert build_skill_prompt("", "do it") == "do it"
        assert build_skill_prompt(None, "do it") == "do it"

    def test_skill_only_when_body_empty(self):
        assert build_skill_prompt("fix-ci", "") == "/fix-ci"


class TestBuildWorkstreamContext:
    def test_includes_pr_details(self):
        ctx = build_workstream_context(
            repo_full_path="posthog/posthog",
            branch="feat/x",
            pr_url="https://github.com/posthog/posthog/pull/7",
            pr={
                "number": 7,
                "title": "My PR",
                "url": "https://github.com/posthog/posthog/pull/7",
                "ciStatus": "failing",
                "reviewDecision": "changes_requested",
                "unresolvedThreads": 2,
            },
        )
        assert "- Repository: posthog/posthog" in ctx
        assert "- Branch: feat/x" in ctx
        assert "- Pull request #7: My PR" in ctx
        assert "CI: failing" in ctx
        assert "Review: changes_requested" in ctx
        assert "Unresolved review threads: 2" in ctx

    def test_falls_back_to_pr_url_without_snapshot(self):
        ctx = build_workstream_context(
            repo_full_path="posthog/posthog", branch="feat/x", pr_url="https://x/pull/1", pr=None
        )
        assert "- Pull request: https://x/pull/1" in ctx

    def test_empty_when_no_context(self):
        assert build_workstream_context(repo_full_path=None, branch=None, pr_url=None, pr=None) == ""


class TestBuildAutoRunPrompt:
    def test_composes_skill_and_context(self):
        prompt = build_auto_run_prompt(
            {"skillId": "fix-ci", "prompt": "Fix CI"},
            repo_full_path="posthog/posthog",
            branch="feat/x",
            pr_url=None,
            pr=None,
        )
        assert prompt.startswith("/fix-ci\n\nFix CI")
        assert "- Repository: posthog/posthog" in prompt
