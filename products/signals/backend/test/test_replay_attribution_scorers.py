import pytest

from products.signals.evals.scorers import AttributionTopPath, normalize_path, relevant_code_paths

_PATHS = ["src/app/files/page.tsx", "src/lib/data.ts"]
_ENVELOPE = '{"previous_finding_correct": false, "finding": {"signal_id": "s1", "relevant_code_paths": ["src/app/files/page.tsx", "src/lib/data.ts"]}}'


class TestReplayAttributionScorers:
    # The agent decides how to wrap its JSON, and it varies run to run. If extraction breaks, every
    # case scores 0 and reads as an attribution regression when it is a parser bug in the eval.
    @pytest.mark.parametrize(
        "message",
        [
            _ENVELOPE,
            f"```json\n{_ENVELOPE}\n```",
            f"Here is the finding.\n\n```\n{_ENVELOPE}\n```\n\nLet me know if you need more.",
            f"I investigated the signal and concluded:\n{_ENVELOPE}",
        ],
    )
    def test_finds_relevant_code_paths_however_the_agent_wrapped_them(self, message: str) -> None:
        assert relevant_code_paths(message) == _PATHS

    @pytest.mark.parametrize(
        "message",
        ["", "I could not determine the code path.", '{"finding": {"signal_id": "s1"}}'],
    )
    def test_returns_none_when_the_message_carries_no_paths(self, message: str) -> None:
        assert relevant_code_paths(message) is None

    # The agent answers with whatever path shape its shell produced, so a correct answer arrives
    # clone-prefixed or `./`-prefixed. Without trimming, a right answer scores 0.
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("src/app/files/page.tsx", "src/app/files/page.tsx"),
            ("./src/app/files/page.tsx", "src/app/files/page.tsx"),
            ("/workspace/hedgebox/src/app/files/page.tsx", "src/app/files/page.tsx"),
            ("`src/app/files/page.tsx`", "src/app/files/page.tsx"),
            ("package.json", "package.json"),
        ],
    )
    def test_normalizes_a_path_to_its_repo_relative_tail(self, raw: str, expected: str) -> None:
        assert normalize_path(raw) == expected

    # Position zero is what downstream work reads, so a right answer ranked third is not a pass.
    @pytest.mark.parametrize(
        "wanted, expected_score",
        [("src/app/files/page.tsx", 1.0), ("src/lib/data.ts", 0.0)],
    )
    def test_top_path_scores_only_the_first_entry(self, wanted: str, expected_score: float) -> None:
        score = AttributionTopPath()._run_eval_sync(
            {"last_message": _ENVELOPE},
            {"attribution_top_path": {"path": wanted}},
        )
        assert score.score == expected_score

    def test_top_path_skips_when_the_case_declares_no_expected_path(self) -> None:
        assert AttributionTopPath()._run_eval_sync({"last_message": _ENVELOPE}, {}).score is None
