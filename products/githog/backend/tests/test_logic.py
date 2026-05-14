"""Tests for githog pure logic — no Django, no DB."""

from textwrap import dedent

from parameterized import parameterized

from products.githog.backend.logic.diff_scanner import (
    extract_event_names,
    extract_flag_keys,
    extract_known_event_mentions,
    extract_known_flag_mentions,
)


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

    def test_includes_context_lines_skips_removed(self) -> None:
        # Removed lines (prefix "-") are no longer in HEAD so are skipped.
        # Context lines (prefix " ") DO appear in HEAD adjacent to the change,
        # so they should be scanned — a PR modifying code near a flag call is
        # materially affected by it.
        diff = dedent(
            """\
            diff --git a/x.py b/x.py
            --- a/x.py
            +++ b/x.py
            @@ -1,3 +1,3 @@
            -if feature_enabled("old-flag", uid):
             if feature_enabled("context-flag", uid):
            +if feature_enabled("new-flag", uid):
            """
        )
        refs = extract_flag_keys(diff)
        assert {r.key for r in refs} == {"new-flag", "context-flag"}

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


class TestExtractEventNames:
    @parameterized.expand(
        [
            ("ts_posthog_capture", "posthog.capture('checkout_started', { plan: 'pro' })", "checkout_started"),
            ("ts_use_posthog_capture", "usePostHog().capture('signup_completed')", "signup_completed"),
            (
                "py_keyword_event",
                "posthoganalytics.capture(distinct_id=uid, event='payment_failed', properties={})",
                "payment_failed",
            ),
            (
                "py_positional_event",
                "posthoganalytics.capture(user.distinct_id, 'invite_sent', {'role': role})",
                "invite_sent",
            ),
            (
                "py_ph_scoped",
                "ph_scoped_capture(team_id=team_id, event='export_started', properties=props)",
                "export_started",
            ),
        ]
    )
    def test_extracts_event(self, _name: str, line: str, expected: str) -> None:
        refs = extract_event_names(_diff("file.py", [line]))
        assert [r.name for r in refs] == [expected]
        assert refs[0].occurrences == 1

    def test_skips_dollar_prefixed_internal_events(self) -> None:
        line = "posthog.capture('$pageview')"
        assert extract_event_names(_diff("x.ts", [line])) == []

    def test_counts_occurrences_and_paths(self) -> None:
        diff = _diff("a.ts", ["posthog.capture('shared_event')", "posthog.capture('shared_event', {})"]) + _diff(
            "b.py", ["posthoganalytics.capture(uid, 'shared_event', {})"]
        )
        refs = extract_event_names(diff)
        assert len(refs) == 1
        assert refs[0].name == "shared_event"
        assert refs[0].occurrences == 3
        assert refs[0].file_paths == ("a.ts", "b.py")

    def test_only_scans_added_lines(self) -> None:
        diff = dedent(
            """\
            diff --git a/x.ts b/x.ts
            --- a/x.ts
            +++ b/x.ts
            @@ -1,2 +1,2 @@
            -posthog.capture('removed_event')
            +posthog.capture('added_event')
            """
        )
        refs = extract_event_names(diff)
        assert [r.name for r in refs] == ["added_event"]


class TestWrappedSDKCalls:
    @parameterized.expand(
        [
            (
                "this_posthog_client",
                'const enabled = await this.posthog.client.isFeatureEnabled("aviationstack-provider", uid)',
                "aviationstack-provider",
            ),
            (
                "injected_client",
                "if (client.isFeatureEnabled('checkout-redesign')) {",
                "checkout-redesign",
            ),
            (
                "service_getter",
                "const v = featureService.getFeatureFlag('billing-v2')",
                "billing-v2",
            ),
        ]
    )
    def test_matches_wrapped_clients(self, _name: str, line: str, expected: str) -> None:
        refs = extract_flag_keys(_diff("file.ts", [line]))
        assert [r.key for r in refs] == [expected]


class TestExtractKnownFlagMentions:
    def test_finds_string_literal_matching_known_key(self) -> None:
        # Modeled on the wrapped-SDK / const-indirected case where the literal
        # appears separately from the call site.
        diff = _diff(
            "providers/featureflagged.ts",
            [
                'const FLAG_KEY = "aviationstack-flight-provider";',
                "const enabled = await this.posthog.client.isFeatureEnabled(FLAG_KEY, uid);",
            ],
        )
        refs = extract_known_flag_mentions(diff, ["aviationstack-flight-provider", "unused-flag"])
        assert [r.key for r in refs] == ["aviationstack-flight-provider"]
        assert refs[0].file_paths == ("providers/featureflagged.ts",)

    def test_skips_keys_below_min_length(self) -> None:
        diff = _diff("x.ts", ['const k = "ab"'])
        assert extract_known_flag_mentions(diff, ["ab"]) == []

    def test_empty_known_keys_returns_empty(self) -> None:
        diff = _diff("x.ts", ['const k = "anything"'])
        assert extract_known_flag_mentions(diff, []) == []

    def test_ignores_keys_only_appearing_as_substrings(self) -> None:
        # "auth" should NOT match because we extract whole string literals.
        diff = _diff("x.ts", ['const url = "https://example.com/auth/login"'])
        assert extract_known_flag_mentions(diff, ["auth"]) == []


class TestExtractKnownEventMentions:
    def test_finds_event_name_literal(self) -> None:
        diff = _diff(
            "service.py",
            ['EVENT = "purchase_completed"', "log_event(user.id, EVENT, props)"],
        )
        refs = extract_known_event_mentions(diff, ["purchase_completed", "signup_started"])
        assert [r.name for r in refs] == ["purchase_completed"]

    def test_skips_dollar_prefixed_known_events(self) -> None:
        diff = _diff("x.ts", ['const e = "$pageview"'])
        assert extract_known_event_mentions(diff, ["$pageview"]) == []
