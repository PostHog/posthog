"""Tests for githog pure logic — no Django, no DB."""

from textwrap import dedent

from parameterized import parameterized

from products.githog.backend.logic.diff_scanner import extract_flag_keys


def _diff(file_path: str, added_lines: list[str]) -> str:
    """Build a minimal unified diff with the given added lines on `file_path`."""
    body = "\n".join(f"+{line}" for line in added_lines)
    return (
        dedent(
            f"""\
        diff --git a/{file_path} b/{file_path}
        --- a/{file_path}
        +++ b/{file_path}
        @@ -1,1 +1,{len(added_lines)} @@
        """
        )
        + body
        + "\n"
    )


class TestExtractFlagKeys:
    @parameterized.expand(
        [
            (
                "python_feature_enabled",
                'if posthoganalytics.feature_enabled("new-onboarding", user.distinct_id):',
                "new-onboarding",
            ),
            ("python_get_feature_flag", 'variant = posthoganalytics.get_feature_flag("billing-v2", uid)', "billing-v2"),
            ("python_bare_feature_enabled", 'if feature_enabled("kill-switch", uid):', "kill-switch"),
            ("js_is_feature_enabled", 'if (posthog.isFeatureEnabled("compact-nav")) {', "compact-nav"),
            ("js_get_feature_flag", 'const v = posthog.getFeatureFlag("checkout-redesign")', "checkout-redesign"),
            ("react_hook", 'const enabled = useFeatureFlag("new-graph")', "new-graph"),
            ("react_hook_enabled", 'const on = useFeatureFlagEnabled("dark-mode")', "dark-mode"),
            ("react_hook_payload", 'const p = useFeatureFlagPayload("home-cta-copy")', "home-cta-copy"),
            ("jsx_flagged_feature", '<FlaggedFeature flag="checkout-v3"><Checkout /></FlaggedFeature>', "checkout-v3"),
            ("jsx_posthog_feature", '<PostHogFeature flag="trial-banner" match={true}>', "trial-banner"),
            ("single_quotes", "if (posthog.isFeatureEnabled('with-single-quotes')) {", "with-single-quotes"),
        ]
    )
    def test_extracts_single_pattern(self, _name: str, line: str, expected_key: str) -> None:
        refs = extract_flag_keys(_diff("file.py", [line]))
        assert [r.key for r in refs] == [expected_key]
        assert refs[0].file_paths == ("file.py",)
        assert refs[0].occurrences == 1

    def test_only_scans_added_lines(self) -> None:
        # Removed lines (prefix "-") should not contribute. Context lines (no prefix) also skipped.
        diff = dedent(
            """\
            diff --git a/x.py b/x.py
            --- a/x.py
            +++ b/x.py
            @@ -1,3 +1,3 @@
            -if feature_enabled("old-flag", uid):
             context_line_with_feature_enabled("context-flag", uid)
            +if feature_enabled("new-flag", uid):
            """
        )
        refs = extract_flag_keys(diff)
        assert {r.key for r in refs} == {"new-flag"}

    def test_constants_surfaced_as_const_prefix(self) -> None:
        line = "if (useFeatureFlag(FEATURE_FLAGS.NEW_DASHBOARD)) {"
        refs = extract_flag_keys(_diff("scene.tsx", [line]))
        # Only the constant reference — useFeatureFlag with a non-literal argument
        # does NOT match the string-literal patterns, by design.
        assert [r.key for r in refs] == ["const:NEW_DASHBOARD"]

    def test_dedups_and_counts_occurrences(self) -> None:
        lines = [
            'if feature_enabled("same-flag", uid):',
            '    log.info(feature_enabled("same-flag", uid))',
            'use_other = useFeatureFlag("other")',
        ]
        refs = extract_flag_keys(_diff("file.py", lines))
        by_key = {r.key: r for r in refs}
        assert by_key["same-flag"].occurrences == 2
        assert by_key["other"].occurrences == 1
        # Sorted by descending occurrences
        assert refs[0].key == "same-flag"

    def test_tracks_file_paths_across_files(self) -> None:
        diff = _diff("backend/foo.py", ['if feature_enabled("shared", uid):']) + _diff(
            "frontend/Bar.tsx", ['useFeatureFlag("shared")']
        )
        refs = extract_flag_keys(diff)
        shared = next(r for r in refs if r.key == "shared")
        assert shared.file_paths == ("backend/foo.py", "frontend/Bar.tsx")
        assert shared.occurrences == 2

    def test_returns_empty_for_diff_without_flags(self) -> None:
        diff = _diff("file.py", ["def some_unrelated_function():", "    return 42"])
        assert extract_flag_keys(diff) == []

    def test_ignores_header_lines_that_look_like_added_lines(self) -> None:
        # "+++" file-header line must not be parsed as added content even though
        # it starts with "+". Build a diff where the path itself contains a
        # would-be flag call — this should NOT register.
        diff = dedent(
            """\
            diff --git a/feature_enabled_helper.py b/feature_enabled_helper.py
            --- a/feature_enabled_helper.py
            +++ b/feature_enabled_helper.py
            @@ -1,1 +1,1 @@
            +pass
            """
        )
        assert extract_flag_keys(diff) == []
