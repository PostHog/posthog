from parameterized import parameterized

from products.signals.backend.temporal.dreaming.instrumentation_gaps import (
    InstrumentationKind,
    PullRequestDiff,
    detect_gaps_across_prs,
    detect_gaps_in_file,
    detect_gaps_in_pr,
)


def _diff(*added_lines: str) -> str:
    return "\n".join(f"+{line}" for line in added_lines)


class TestInstrumentationGapDetection:
    def test_new_view_without_capture_flags_product_analytics(self):
        gaps = detect_gaps_in_file("app/views.py", _diff("def checkout_view(request):", "    return render(request)"))
        kinds = {g.kind for g in gaps}
        assert InstrumentationKind.PRODUCT_ANALYTICS in kinds

    def test_new_view_with_capture_is_clean(self):
        gaps = detect_gaps_in_file(
            "app/views.py",
            _diff(
                "def checkout_view(request):", "    posthog.capture('checkout_completed')", "    return render(request)"
            ),
        )
        assert all(g.kind != InstrumentationKind.PRODUCT_ANALYTICS for g in gaps)

    def test_swallowed_except_flags_error_tracking(self):
        gaps = detect_gaps_in_file("app/jobs.py", _diff("try:", "    do_thing()", "except Exception:", "    pass"))
        assert any(g.kind == InstrumentationKind.ERROR_TRACKING for g in gaps)

    def test_except_that_reraises_is_clean(self):
        gaps = detect_gaps_in_file("app/jobs.py", _diff("except Exception:", "    log.error('x')", "    raise"))
        assert all(g.kind != InstrumentationKind.ERROR_TRACKING for g in gaps)

    def test_except_with_capture_exception_is_clean(self):
        gaps = detect_gaps_in_file("app/jobs.py", _diff("except Exception as e:", "    capture_exception(e)"))
        assert all(g.kind != InstrumentationKind.ERROR_TRACKING for g in gaps)

    def test_js_catch_without_report_flags_error_tracking(self):
        gaps = detect_gaps_in_file("app/foo.ts", _diff("try {", "  doThing()", "} catch (e) {", "  // ignore", "}"))
        assert any(g.kind == InstrumentationKind.ERROR_TRACKING for g in gaps)

    def test_raw_openai_call_flags_llm_analytics(self):
        gaps = detect_gaps_in_file(
            "app/ai.py", _diff("client = OpenAI()", "resp = client.chat.completions.create(model='gpt-4')")
        )
        assert any(g.kind == InstrumentationKind.LLM_ANALYTICS for g in gaps)

    def test_llm_call_with_observability_is_clean(self):
        gaps = detect_gaps_in_file(
            "app/ai.py",
            _diff("from posthog.ai import OpenAI", "client = OpenAI()", "resp = client.chat.completions.create()"),
        )
        assert all(g.kind != InstrumentationKind.LLM_ANALYTICS for g in gaps)

    def test_anthropic_messages_create_flags_llm(self):
        gaps = detect_gaps_in_file(
            "app/ai.py", _diff("client = Anthropic()", "msg = client.messages.create(model='claude')")
        )
        assert any(g.kind == InstrumentationKind.LLM_ANALYTICS for g in gaps)

    @parameterized.expand(
        [
            ("test file python", "app/test_views.py"),
            ("test file ts", "app/foo.test.ts"),
            ("spec file", "app/foo.spec.tsx"),
            ("generated", "frontend/src/generated/views.py"),
            ("migration", "app/migrations/0001_init.py"),
            ("node_modules", "node_modules/pkg/index.js"),
            ("declaration", "types/foo.d.ts"),
        ]
    )
    def test_skipped_paths_never_flag(self, _name, path):
        gaps = detect_gaps_in_file(path, _diff("def create_view(request):", "    pass"))
        assert gaps == []

    @parameterized.expand(
        [
            ("markdown", "README.md"),
            ("yaml", "config.yaml"),
            ("lockfile", "pnpm-lock.yaml"),
        ]
    )
    def test_non_source_suffixes_skipped(self, _name, path):
        gaps = detect_gaps_in_file(path, _diff("def create_view():", "    OpenAI()"))
        assert gaps == []

    def test_only_added_lines_considered(self):
        # A pre-existing (context / removed) line with a swallowed except must not flag.
        diff = "\n".join([" try:", "-except Exception:", "-    pass", "+    return 1"])
        gaps = detect_gaps_in_file("app/x.py", diff)
        assert gaps == []

    def test_at_most_one_gap_per_kind_per_file(self):
        gaps = detect_gaps_in_file(
            "app/x.py",
            _diff("except Exception:", "    pass", "except ValueError:", "    pass"),
        )
        error_gaps = [g for g in gaps if g.kind == InstrumentationKind.ERROR_TRACKING]
        assert len(error_gaps) == 1

    def test_multiple_kinds_in_one_file(self):
        gaps = detect_gaps_in_file(
            "app/x.py",
            _diff(
                "def submit_handler(request):",
                "    client = OpenAI()",
                "    client.chat.completions.create()",
                "    try:",
                "        pass",
                "    except Exception:",
                "        pass",
            ),
        )
        kinds = {g.kind for g in gaps}
        assert kinds == {
            InstrumentationKind.PRODUCT_ANALYTICS,
            InstrumentationKind.LLM_ANALYTICS,
            InstrumentationKind.ERROR_TRACKING,
        }

    def test_detect_gaps_in_pr_aggregates_files(self):
        pr = PullRequestDiff(
            number=42,
            title="add feature",
            merged_at="2026-06-19T00:00:00Z",
            author="alice",
            files={
                "app/views.py": _diff("def create_view(request):", "    pass"),
                "app/clean.py": _diff("def helper():", "    return posthog.capture('x')"),
            },
        )
        result = detect_gaps_in_pr(pr)
        assert result.pr_number == 42
        assert len(result.gaps) == 1
        assert result.gaps[0].file_path == "app/views.py"

    def test_detect_across_prs_drops_clean_prs(self):
        clean = PullRequestDiff(1, "clean", "t", "a", {"a.py": _diff("x = 1")})
        dirty = PullRequestDiff(2, "dirty", "t", "a", {"b.py": _diff("def create_view():", "    pass")})
        results = detect_gaps_across_prs([clean, dirty])
        assert [r.pr_number for r in results] == [2]
