from parameterized import parameterized

from products.foundry.backend.logic import gauntlet

_DIFF_TWO_ADDED_LINES = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,3 +1,5 @@
 line1
+added_line_2
+added_line_3
 line4
 line5
"""

_LCOV_REPORT = "SF:app.py\nDA:2,1\nDA:3,0\nend_of_record\n"

_COBERTURA_REPORT = """<coverage>
  <packages>
    <package name="app">
      <classes>
        <class name="app" filename="app.py">
          <lines>
            <line number="2" hits="1"/>
            <line number="3" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


def _mutation_junitxml(killed: int, survived: int) -> str:
    cases = "".join(f'<testcase classname="m" name="killed_{i}"></testcase>' for i in range(killed))
    cases += "".join(
        f'<testcase classname="m" name="survived_{i}"><failure message="survived"/></testcase>' for i in range(survived)
    )
    return f"<testsuite>{cases}</testsuite>"


class TestDiffParsing:
    def test_changed_files_from_diff(self) -> None:
        assert gauntlet.changed_files_from_diff(_DIFF_TWO_ADDED_LINES) == ["app.py"]

    def test_added_lines_by_file_tracks_post_image_line_numbers(self) -> None:
        """A hunk's `+` lines land at their new-file line number, not their position in the
        diff — this is what changed-line coverage keys off of, so getting it wrong silently
        breaks the coverage check for any file with more than one hunk."""
        assert gauntlet.added_lines_by_file(_DIFF_TWO_ADDED_LINES) == {"app.py": {2, 3}}

    def test_added_line_text_by_file_captures_content_not_just_line_numbers(self) -> None:
        assert gauntlet.added_line_text_by_file(_DIFF_TWO_ADDED_LINES) == {"app.py": ["added_line_2", "added_line_3"]}


class TestCoverageReportParsing:
    def test_parse_lcov(self) -> None:
        assert gauntlet.parse_lcov(_LCOV_REPORT) == {"app.py": {2: 1, 3: 0}}

    def test_parse_cobertura(self) -> None:
        assert gauntlet.parse_cobertura(_COBERTURA_REPORT) == {"app.py": {2: 1, 3: 0}}

    @parameterized.expand(
        [
            ("lcov", _LCOV_REPORT),
            ("cobertura", _COBERTURA_REPORT),
        ]
    )
    def test_coverage_check_outcome_boundary(self, report_format: str, report_content: str) -> None:
        """1 of 2 changed lines covered = 50% — the boundary case must pass at exactly the
        threshold and fail one point above it, in both supported report formats."""
        at_threshold = gauntlet.coverage_check_outcome(
            diff_text=_DIFF_TWO_ADDED_LINES,
            report_content=report_content,
            report_format=report_format,
            min_changed_line_pct=50.0,
        )
        assert at_threshold.passed is True

        above_threshold = gauntlet.coverage_check_outcome(
            diff_text=_DIFF_TWO_ADDED_LINES,
            report_content=report_content,
            report_format=report_format,
            min_changed_line_pct=50.1,
        )
        assert above_threshold.passed is False

    def test_coverage_check_outcome_with_no_added_lines_passes_trivially(self) -> None:
        outcome = gauntlet.coverage_check_outcome(
            diff_text="", report_content=_LCOV_REPORT, report_format="lcov", min_changed_line_pct=100.0
        )
        assert outcome.passed is True
        assert "no added/changed lines" in outcome.detail

    def test_coverage_check_outcome_unknown_format(self) -> None:
        outcome = gauntlet.coverage_check_outcome(
            diff_text=_DIFF_TWO_ADDED_LINES, report_content="", report_format="bogus", min_changed_line_pct=0
        )
        assert outcome.passed is False


class TestMutationReportParsing:
    def test_parse_mutation_junitxml(self) -> None:
        pct, killed, total = gauntlet.parse_mutation_junitxml(_mutation_junitxml(killed=2, survived=1))
        assert (killed, total) == (2, 3)
        assert round(pct, 2) == 66.67

    @parameterized.expand(
        [
            (60.0, True),
            (66.7, False),
        ]
    )
    def test_mutation_check_outcome_boundary(self, min_score_pct: float, expected_pass: bool) -> None:
        """2/3 killed = 66.67% — passes at a lower bar, fails just above the actual score."""
        outcome = gauntlet.mutation_check_outcome(
            report_content=_mutation_junitxml(killed=2, survived=1), min_score_pct=min_score_pct
        )
        assert outcome.passed is expected_pass

    def test_mutation_check_outcome_no_mutants_fails(self) -> None:
        """An empty mutation report (mutmut found nothing to mutate) must not silently pass —
        that would let a required mutation check rubber-stamp a change nothing was tested."""
        outcome = gauntlet.mutation_check_outcome(
            report_content=_mutation_junitxml(killed=0, survived=0), min_score_pct=0
        )
        assert outcome.passed is False
        assert "no mutants" in outcome.detail

    def test_resolve_mutation_command_with_custom_template_trusts_it_as_is(self) -> None:
        """A configured template isn't mutmut-specific — it must not silently drop non-.py
        files the way the built-in default deliberately does."""
        command = gauntlet.resolve_mutation_command("mutmut run --paths-to-mutate {files}", ["app.py", "README.md"])
        assert "app.py" in command and "README.md" in command

    def test_resolve_mutation_command_default_restricts_to_python_files(self) -> None:
        command = gauntlet.resolve_mutation_command("", ["app.py", "README.md"])
        assert "app.py" in command
        assert "README.md" not in command

    def test_resolve_mutation_command_falls_back_to_whole_tree_when_no_python_files_changed(self) -> None:
        """The built-in mutmut default has nothing to restrict to when a diff touches no .py
        files — it must mutate the whole tree rather than pass mutmut an empty path list."""
        command = gauntlet.resolve_mutation_command("", ["README.md"])
        assert "--paths-to-mutate ." in command


class TestProtectedPaths:
    def test_touching_a_protected_path_fails_and_names_it(self) -> None:
        """The Uncle-Bob invariant: a builder diff touching a protected test file must fail
        with a violation that names the exact path, not a generic message."""
        outcome = gauntlet.protected_paths_check_outcome(
            changed_files=["tests/acceptance/test_checkout.py", "src/app.py"],
            protected_paths=["tests/acceptance/"],
        )
        assert outcome.passed is False
        assert "tests/acceptance/test_checkout.py" in outcome.detail

    def test_not_touching_protected_paths_passes(self) -> None:
        outcome = gauntlet.protected_paths_check_outcome(
            changed_files=["src/app.py"], protected_paths=["tests/acceptance/"]
        )
        assert outcome.passed is True


class TestFlagGuard:
    def test_unguarded_change_fails(self) -> None:
        diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,2 @@\n line1\n+unrelated_change\n"
        outcome = gauntlet.flag_guard_check_outcome(
            diff_text=diff, changed_files=["app.py"], flag_key="bet-my-slug", exempt_paths=[]
        )
        assert outcome.passed is False
        assert "app.py" in outcome.detail

    def test_guarded_change_passes(self) -> None:
        diff = (
            "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,2 @@\n"
            " line1\n+if flags.get('bet-my-slug'):\n"
        )
        outcome = gauntlet.flag_guard_check_outcome(
            diff_text=diff, changed_files=["app.py"], flag_key="bet-my-slug", exempt_paths=[]
        )
        assert outcome.passed is True

    def test_exempt_path_is_not_flagged(self) -> None:
        diff = "diff --git a/tests/x.py b/tests/x.py\n--- a/tests/x.py\n+++ b/tests/x.py\n@@ -1,1 +1,2 @@\n line1\n+assert True\n"
        outcome = gauntlet.flag_guard_check_outcome(
            diff_text=diff, changed_files=["tests/x.py"], flag_key="bet-my-slug", exempt_paths=["tests/"]
        )
        assert outcome.passed is True

    def test_no_flag_key_configured_skips(self) -> None:
        outcome = gauntlet.flag_guard_check_outcome(
            diff_text=_DIFF_TWO_ADDED_LINES, changed_files=["app.py"], flag_key="", exempt_paths=[]
        )
        assert outcome.passed is True
