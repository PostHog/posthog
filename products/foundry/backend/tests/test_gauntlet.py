import json

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


def _mutation_cicd_stats(killed: int, survived: int) -> str:
    return json.dumps({"killed": killed, "survived": survived, "total": killed + survived})


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
    def test_parse_mutation_cicd_stats(self) -> None:
        pct, killed, total = gauntlet.parse_mutation_cicd_stats(_mutation_cicd_stats(killed=2, survived=1))
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
            report_content=_mutation_cicd_stats(killed=2, survived=1), min_score_pct=min_score_pct
        )
        assert outcome.passed is expected_pass

    def test_mutation_check_outcome_no_mutants_fails(self) -> None:
        """An empty mutation report (mutmut found nothing to mutate) must not silently pass —
        that would let a required mutation check rubber-stamp a change nothing was tested."""
        outcome = gauntlet.mutation_check_outcome(
            report_content=_mutation_cicd_stats(killed=0, survived=0), min_score_pct=0
        )
        assert outcome.passed is False
        assert "no mutants" in outcome.detail

    def test_resolve_mutation_command_with_custom_template_fills_files_placeholder(self) -> None:
        """A configured template is trusted as-is, including any {files} placeholder — unlike
        the built-in default, which mutmut 3.x's CLI no longer lets us restrict by path."""
        command = gauntlet.resolve_mutation_command("some-tool --paths {files}", ["app.py", "README.md"])
        assert "app.py" in command and "README.md" in command

    def test_resolve_mutation_command_default_ignores_changed_files(self) -> None:
        """mutmut 3.x dropped --paths-to-mutate; the built-in default relies on the artifact
        repo's own [tool.mutmut] source_paths config instead of any per-run file list."""
        command = gauntlet.resolve_mutation_command("", ["app.py", "README.md"])
        assert command == "mutmut run; mutmut export-cicd-stats"


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
