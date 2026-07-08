import json
from pathlib import Path

import pytest

from backtest_lib import RUN_DIR_RE, load_manifest, message_text, rewrite_diff_path, split_trace_input
from parameterized import parameterized

TRACED_PATH_INPUT = [
    {"role": "system", "content": "You decide whether a pull request is safe."},
    {"role": "user", "content": "Review PR #1.\nDiff: /home/runner/work/posthog/posthog/.pr-review-diff.patch"},
]

GATEWAY_INPUT = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "<system-reminder>\ninjected CLAUDE.md contents\n</system-reminder>"},
            {"type": "text", "text": "Review PR #2.\nDiff: /home/runner/work/posthog/posthog/.pr-review-diff.patch"},
        ],
    },
    {"role": "assistant", "content": [{"type": "text", "text": "thinking"}]},
]


class TestTraceParsing:
    def test_traced_path_input_splits_system_and_user(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.json"
        trace.write_text(json.dumps(TRACED_PATH_INPUT))
        system, user = split_trace_input(trace)
        assert system == "You decide whether a pull request is safe."
        assert user.startswith("Review PR #1.")

    def test_gateway_input_strips_reminders_and_has_no_system(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.json"
        trace.write_text(json.dumps(GATEWAY_INPUT))
        system, user = split_trace_input(trace)
        assert system == ""
        assert "<system-reminder>" not in user
        assert user.startswith("Review PR #2.")

    def test_no_user_message_raises(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.json"
        trace.write_text(json.dumps([{"role": "system", "content": "sys"}]))
        with pytest.raises(ValueError):
            split_trace_input(trace)

    def test_reminder_only_kept_when_not_stripping(self) -> None:
        message = GATEWAY_INPUT[0]
        assert "<system-reminder>" in message_text(message)


class TestDiffPathRewrite:
    @parameterized.expand(
        [
            ("absolute_runner_path", "Diff at /home/runner/work/posthog/posthog/.pr-review-diff.patch here"),
            ("relative_path", "Diff at .pr-review-diff.patch here"),
            ("per_trace_suffix", "Diff at /ci/.pr-review-diff-abc123.patch here"),
        ]
    )
    def test_rewrites_any_diff_reference(self, _name: str, prompt: str) -> None:
        rewritten = rewrite_diff_path(prompt, Path("/local/repo/.pr-review-diff-x.patch"))
        assert "/local/repo/.pr-review-diff-x.patch" in rewritten
        assert "runner" not in rewritten and "/ci/" not in rewritten

    def test_leaves_unrelated_paths_alone(self) -> None:
        prompt = "See migrations/0001_initial.py and config.patch"
        assert rewrite_diff_path(prompt, Path("/x.patch")) == prompt


class TestCohortLoading:
    def _write_manifest(self, tmp_path: Path, rows: list[dict]) -> None:
        (tmp_path / "manifest.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    def _row(self, **overrides: object) -> dict:
        row = {
            "repo": "PostHog/posthog",
            "pr": 1,
            "cohort": "2.0.0b1",
            "gate_verdict": "PENDING",
            "trace_id": "aaa",
        }
        row.update(overrides)
        return row

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"repo": "PostHog/code"}, id="other-repo"),
            pytest.param({"gate_verdict": "DENIED"}, id="gate-denied"),
            pytest.param({"gate_verdict": "AUTO-APPROVED"}, id="gate-auto-approved"),
            pytest.param({"trace_id": None}, id="no-trace"),
            pytest.param({"cohort": "unmarked"}, id="other-cohort"),
        ],
    )
    def test_excludes(self, overrides: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STAMPHOG_BACKTEST_DATA", str(tmp_path))
        self._write_manifest(tmp_path, [self._row(), self._row(**{"pr": 2, "trace_id": "bbb", **overrides})])
        rows = load_manifest("2.0.0b1")
        assert [r["pr"] for r in rows] == [1]

    def test_all_gates_keeps_denied_rows(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STAMPHOG_BACKTEST_DATA", str(tmp_path))
        self._write_manifest(tmp_path, [self._row(), self._row(pr=2, trace_id="bbb", gate_verdict="DENIED")])
        assert len(load_manifest("2.0.0b1", discretionary_only=False)) == 2


class TestRunDirParsing:
    @parameterized.expand(
        [
            ("simple", "2.0.0b1_current_rep1", ("2.0.0b1", "current", "1")),
            ("file_arm_with_underscore", "unmarked_my_prompt_rep2", ("unmarked", "my_prompt", "2")),
        ]
    )
    def test_parses(self, _name: str, dirname: str, expected: tuple[str, str, str]) -> None:
        match = RUN_DIR_RE.match(dirname)
        assert match is not None
        assert (match["cohort"], match["arm"], match["rep"]) == expected

    def test_rejects_non_run_dirs(self) -> None:
        assert RUN_DIR_RE.match("traces") is None
