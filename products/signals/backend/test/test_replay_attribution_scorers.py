import json

import pytest

from products.signals.evals import scout_prompts
from products.signals.evals.scorers import (
    AnchorNamed,
    AnchorTier,
    AttributionTopPath,
    ElementNotInvented,
    normalize_path,
    relevant_code_paths,
)
from products.signals.evals.scout_prompts import SkillSectionMissingError, skill_section

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

    # The scout answers with a literal a human typed, so an answer that drops a trailing colon or
    # changes case is the same anchor. Matching too tightly reads as a regression in the scout body;
    # matching a bare word matches half the repo and reads as a pass that found nothing.
    @pytest.mark.parametrize(
        "got, expected_score",
        [
            ("📤 Upload file", 1.0),
            ("`📤 Upload file`", 1.0),
            ("Upload file", 1.0),
            ("upload   file", 1.0),
            ("Pay now", 0.0),
            ("btn", 0.0),
            ("", 0.0),
        ],
    )
    def test_anchor_matches_a_literal_the_agent_reworded_but_not_a_different_one(
        self, got: str, expected_score: float
    ) -> None:
        score = AnchorNamed()._run_eval_sync(
            {"last_message": json.dumps({"anchor": got, "tier": "text", "element_known": True})},
            {"anchor_named": {"anchor": "📤 Upload file", "tier": "text"}},
        )
        assert score.score == expected_score

    # An exception anchor is a path, so it arrives clone-prefixed like the research cases' answers do.
    def test_anchor_compares_an_exception_answer_as_a_path(self) -> None:
        score = AnchorNamed()._run_eval_sync(
            {"last_message": json.dumps({"anchor": "/workspace/hedgebox/src/lib/data.ts", "tier": "exception"})},
            {"anchor_named": {"anchor": "src/lib/data.ts", "tier": "exception"}},
        )
        assert score.score == 1.0

    @pytest.mark.parametrize("got, expected_score", [("text", 1.0), ("Text", 1.0), ("identifier", 0.0)])
    def test_tier_ignores_case_but_not_the_wrong_tier(self, got: str, expected_score: float) -> None:
        score = AnchorTier()._run_eval_sync(
            {"last_message": json.dumps({"anchor": "x", "tier": got})},
            {"anchor_tier": {"tier": "text"}},
        )
        assert score.score == expected_score

    # The one failure the recipe warns about by name. An agent that omits the field has not said the
    # element is unknown, so treating a missing key as a pass would let an invention through.
    @pytest.mark.parametrize(
        "answer, expected_score",
        [
            ({"anchor": "/pricing", "tier": "route", "element_known": False}, 1.0),
            ({"anchor": "/pricing", "tier": "route", "element_known": True}, 0.0),
            ({"anchor": "/pricing", "tier": "route"}, 0.0),
        ],
    )
    def test_element_not_invented_needs_an_explicit_denial(self, answer: dict, expected_score: float) -> None:
        score = ElementNotInvented()._run_eval_sync(
            {"last_message": json.dumps(answer)},
            {"element_not_invented": {}},
        )
        assert score.score == expected_score

    # The scout prompts quote the skill body, so a renamed or deleted section would otherwise ship a
    # prompt with no attribution guidance in it and score the cases against nothing.
    @pytest.mark.parametrize("scout", ["session_replay", "replay_vision"])
    def test_skill_section_reads_the_scout_body(self, scout: str) -> None:
        assert "$exception_sources" in skill_section(scout)

    def test_skill_section_fails_loudly_when_the_heading_is_gone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(scout_prompts._SECTION_BY_SCOUT, "session_replay", "#### Gone")
        with pytest.raises(SkillSectionMissingError):
            skill_section("session_replay")
