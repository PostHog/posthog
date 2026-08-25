"""Unit tests for stack-path disambiguation in repo selection (#86091)."""

from products.tasks.backend.logic.repo_selection.agent import (
    apply_stack_path_disambiguation,
    extract_code_paths_from_context,
    prefer_explicit_repo_mention,
    _tree_contains_path,
)
from products.tasks.backend.logic.repo_selection.types import RepoSelectionResult


class TestExtractCodePathsFromContext:
    def test_extracts_stack_style_paths(self):
        context = """
        Error at src/routes/api/users/+server.ts:12
        Also in packages/app/lib/pocketbase.ts
        """
        paths = extract_code_paths_from_context(context)
        assert "src/routes/api/users/+server.ts" in paths
        assert "packages/app/lib/pocketbase.ts" in paths

    def test_skips_node_modules_and_urls(self):
        context = """
        node_modules/foo/bar.js
        https://cdn.example.com/app/main.js
        src/real/file.ts
        """
        paths = extract_code_paths_from_context(context)
        assert paths == ["src/real/file.ts"]

    def test_dedupes_case_insensitively(self):
        context = "Src/App.ts and src/app.ts"
        paths = extract_code_paths_from_context(context)
        assert len(paths) == 1


class TestTreeContainsPath:
    def test_exact_and_suffix_match(self):
        tree = "src/routes/+page.svelte\nlib/utils.ts\n"
        assert _tree_contains_path(tree, "src/routes/+page.svelte")
        assert _tree_contains_path(tree, "lib/utils.ts")
        assert not _tree_contains_path(tree, "src/missing.ts")


class TestPreferExplicitRepoMention:
    def test_single_owner_repo_mention(self):
        assert (
            prefer_explicit_repo_mention(
                "Please fix acme/instrumented-app session bugs",
                ["acme/instrumented-app", "acme/other-app"],
            )
            == "acme/instrumented-app"
        )

    def test_github_url_mention(self):
        assert (
            prefer_explicit_repo_mention(
                "See https://github.com/acme/instrumented-app/issues/1",
                ["acme/instrumented-app", "acme/other-app"],
            )
            == "acme/instrumented-app"
        )

    def test_ambiguous_mentions_return_none(self):
        assert (
            prefer_explicit_repo_mention(
                "Compare acme/instrumented-app and acme/other-app",
                ["acme/instrumented-app", "acme/other-app"],
            )
            is None
        )


class TestApplyStackPathDisambiguation:
    def test_keeps_selection_when_paths_hit(self):
        result = RepoSelectionResult(repository="acme/app-a", reason="agent pick")
        out = apply_stack_path_disambiguation(
            result,
            paths=["src/routes/+page.svelte"],
            path_hits={"acme/app-a": ["src/routes/+page.svelte"], "acme/app-b": []},
        )
        assert out.repository == "acme/app-a"

    def test_overrides_when_single_other_repo_has_paths(self):
        result = RepoSelectionResult(
            repository="acme/wrong-app",
            reason="unique SvelteKit + PocketBase architecture",
            task_id="task-1",
        )
        out = apply_stack_path_disambiguation(
            result,
            paths=["src/routes/api/billing/+server.ts"],
            path_hits={
                "acme/wrong-app": [],
                "acme/instrumented-app": ["src/routes/api/billing/+server.ts"],
            },
        )
        assert out.repository == "acme/instrumented-app"
        assert out.task_id == "task-1"
        assert "Overrode" in out.reason
        assert "disqualify" in out.reason.lower() or "Absent stack paths" in out.reason

    def test_returns_null_when_multiple_path_repos_and_pick_has_none(self):
        result = RepoSelectionResult(repository="acme/wrong", reason="architecture")
        out = apply_stack_path_disambiguation(
            result,
            paths=["src/foo.ts"],
            path_hits={
                "acme/wrong": [],
                "acme/a": ["src/foo.ts"],
                "acme/b": ["src/foo.ts"],
            },
        )
        assert out.repository is None
        assert "Requires human input" in out.reason or "human input" in out.reason.lower()

    def test_noop_without_paths(self):
        result = RepoSelectionResult(repository="acme/app", reason="only choice")
        out = apply_stack_path_disambiguation(result, paths=[], path_hits={"acme/app": []})
        assert out.repository == "acme/app"
