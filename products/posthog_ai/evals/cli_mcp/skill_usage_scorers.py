"""Scorers for the skill-usage eval — the layer above skill *distribution*.

Distribution scorers (``skill_distribution_scorers``) grade whether the agent found
and loaded the right skill. These grade what it did with the skill once loaded:
pulling the reference files the skill points at, recovering from a zero-hit search
instead of giving up, and answering the question with the facts the skill teaches.

Every scorer self-skips (``Score(score=None)``) when its ``expected`` key is absent,
so one global scorer list works across every case — Braintrust drops ``None`` from
per-metric aggregates.
"""

from __future__ import annotations

import json
from typing import Any, cast

from braintrust import Score
from braintrust_core.score import Scorer

from products.posthog_ai.eval_harness.harness.cli import SkillDelivery
from products.posthog_ai.eval_harness.log_parser import EXEC_TOOL_NAME, LogParser, ToolCall, normalize_tool_name
from products.posthog_ai.eval_harness.scorers import BINARY_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.evals.cli_mcp.skill_distribution_scorers import (
    _exec_command,
    _expected_spec,
    _is_qualified_skill_token,
    _parser,
    _qualified_skill,
    _skill_search_calls,
    _successful_exec_calls,
    skill_distribution_expectations,
)

_ZERO_HIT_PREFIX = 'No skills matched "'


def _exec_calls(parser: LogParser) -> list[ToolCall]:
    return [call for call in parser.get_tool_calls() if normalize_tool_name(call.raw_name) == EXEC_TOOL_NAME]


class ExpectedReferencePulled(Scorer):
    """Binary: did the agent read one of the skill's reference files (not just the skill)?

    A skill's ``SKILL.md`` points at reference files under ``references/`` that hold the
    detail needed to answer well. This checks the agent actually pulled one — via
    ``learn <qualified> <path>`` in exec mode, or a native file read of the bundled
    skill's reference in bundled mode. A bare skill load or all-qualified batch load
    does not count.
    """

    def _name(self) -> str:
        return "expected_reference_pulled"

    def _run_eval_sync(
        self,
        output: dict[str, object] | None,
        expected: dict[str, object] | None = None,
        **kwargs: object,
    ) -> Score:
        spec = _expected_spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Scorer does not apply"})
        skill = spec.get("skill")
        delivery = spec.get("delivery")
        source = spec.get("source", "posthog")
        paths = spec.get("paths")
        if (
            not isinstance(skill, str)
            or not skill
            or delivery not in ("bundled", "exec")
            or source not in ("posthog", "project")
            or not isinstance(paths, list)
            or not paths
            or not all(isinstance(path, str) and path for path in paths)
        ):
            return Score(name=self._name(), score=0.0, metadata={"reason": "Invalid scorer expectation"})
        parser = _parser(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        accepted = [cast(str, path) for path in paths]
        if delivery == "exec":
            matched = self._exec_match(parser, cast(str, skill), cast(str, source), accepted)
        else:
            matched = self._bundled_match(parser, cast(str, skill), accepted)
        if matched is not None:
            return Score(name=self._name(), score=1.0, metadata=matched)
        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": "No expected reference file was pulled", "skill": skill, "paths": accepted},
        )

    def _exec_match(self, parser: LogParser, skill: str, source: str, accepted: list[str]) -> dict[str, object] | None:
        qualified = _qualified_skill(skill, source)
        for call in _successful_exec_calls(parser):
            verb, rest = _exec_command(call)
            if verb != "learn":
                continue
            tokens = rest.split()
            if not tokens or tokens[0] != qualified or len(tokens) <= 1:
                continue
            # An all-qualified token list is a batch skill load (`learn posthog:a posthog:b`),
            # not a reference pull.
            if all(_is_qualified_skill_token(token) for token in tokens):
                continue
            for token in self._path_tokens(tokens[1:]):
                normalized = token[2:] if token.startswith("./") else token
                for path in accepted:
                    if token == path or normalized == path:
                        return {"call_id": call.call_id, "matched_path": path}
        return None

    @staticmethod
    def _path_tokens(rest_tokens: list[str]) -> list[str]:
        # Path tokens run until the first scoped-search / line-range flag; anything after
        # that is search or slicing arguments, not a file path.
        tokens: list[str] = []
        for token in rest_tokens:
            if token in ("-s", "--lines"):
                break
            tokens.append(token)
        return tokens

    def _bundled_match(self, parser: LogParser, skill: str, accepted: list[str]) -> dict[str, object] | None:
        for call in parser.get_tool_calls():
            if call.is_error:
                continue
            reference = f"{call.name}\n{json.dumps(call.input, default=str)}".lower()
            for path in accepted:
                if f"{skill}/{path}".lower() in reference:
                    return {"call_id": call.call_id, "matched_path": path}
        return None


class SearchRecoveryAfterZeroHit(Scorer):
    """Binary: after a zero-hit skill search, did the agent keep learning rather than give up?

    A ``learn -s`` that matches nothing returns text starting with ``No skills matched "``.
    The right move is another ``learn`` command (broaden the query, list skills, describe) —
    not to jump straight into product tools guessing. Self-skips when no zero-hit search ran.
    """

    def _name(self) -> str:
        return "search_recovery_after_zero_hit"

    def _run_eval_sync(
        self,
        output: dict[str, object] | None,
        expected: dict[str, object] | None = None,
        **kwargs: object,
    ) -> Score:
        if _expected_spec(expected, self._name()) is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Scorer does not apply"})
        parser = _parser(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        zero_hits = [call for call in _skill_search_calls(parser) if call.output.startswith(_ZERO_HIT_PREFIX)]
        if not zero_hits:
            return Score(name=self._name(), score=None, metadata={"reason": "No zero-hit search occurred"})

        # Ordering must see errored calls too: a gate-rejected product call after a
        # zero-hit search is still the agent jumping to product tools, even though
        # the agent may run `learn` right after the rejection.
        exec_calls = _exec_calls(parser)
        for zero_hit in zero_hits:
            following = [call for call in exec_calls if call.position > zero_hit.position]
            if not following:
                return Score(
                    name=self._name(),
                    score=0.0,
                    metadata={"reason": "No learning follow-up after zero-hit search", "call_id": zero_hit.call_id},
                )
            nxt = min(following, key=lambda call: call.position)
            verb, rest = _exec_command(nxt)
            if verb != "learn":
                return Score(
                    name=self._name(),
                    score=0.0,
                    metadata={
                        "reason": "A non-learning command followed a zero-hit search",
                        "call_id": nxt.call_id,
                        "command": f"{verb} {rest}".strip(),
                    },
                )
        return Score(name=self._name(), score=1.0, metadata={"zero_hits": len(zero_hits)})


SKILL_ANSWER_PROMPT = """
You are judging whether an agent's final answer states every fact from an expected answer.

The agent was asked USER_PROMPT and produced FINAL_MESSAGE. EXPECTED_ANSWER lists the facts the final message must convey.

Grade only whether FINAL_MESSAGE states every fact in EXPECTED_ANSWER:
- Paraphrase is fine — the wording does not need to match.
- Numeric values must match; a different number is a failure.
- Extra correct material in FINAL_MESSAGE is fine and never a reason to fail.
- Missing or contradicting any fact from EXPECTED_ANSWER is a failure.

<user_prompt>
{{output.prompt}}
</user_prompt>

<expected_answer>
{{expected.expected_answer}}
</expected_answer>

<final_message>
{{output.final_message}}
</final_message>

Does the final message state every fact in the expected answer? Answer `yes` or `no`.
""".strip()


class SkillAnswerCorrectness(JudgedScorer):
    """Binary LLM judge: does the final message state every fact the skill's answer requires?

    Self-skips (``None``) when not requested. Scores 0.0 (not ``None``) when the expected
    answer is missing/blank or the agent produced no final message, so a broken run surfaces
    as a failing score rather than being silently dropped from the aggregate.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="skill_answer_correctness",
            prompt_template=SKILL_ANSWER_PROMPT,
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        spec = _expected_spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Scorer does not apply"})
        expected_answer = spec.get("expected_answer")
        if not isinstance(expected_answer, str) or not expected_answer.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No expected answer configured"})
        last_message = output.get("last_message") if isinstance(output, dict) else None
        if not isinstance(last_message, str) or not last_message.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final agent message"})
        prompt = output.get("prompt") if isinstance(output, dict) else ""
        return {
            "output": {"prompt": prompt if isinstance(prompt, str) else "", "final_message": last_message},
            "expected": {"expected_answer": expected_answer},
        }


def skill_usage_expectations(
    skill: str,
    downstream_tools: list[str],
    skill_delivery: SkillDelivery,
    *,
    source: str = "posthog",
    reference_paths: list[str] | None = None,
    expected_answer: str | None = None,
) -> dict[str, dict[str, object]]:
    expectations = skill_distribution_expectations(skill, downstream_tools, skill_delivery, source=source)
    if reference_paths:
        expectations["expected_reference_pulled"] = {
            "skill": skill,
            "delivery": skill_delivery,
            "source": source,
            "paths": reference_paths,
        }
    if expected_answer:
        expectations["skill_answer_correctness"] = {"expected_answer": expected_answer}
    if skill_delivery == "exec":
        expectations["search_recovery_after_zero_hit"] = {}
    return expectations


__all__ = [
    "ExpectedReferencePulled",
    "SearchRecoveryAfterZeroHit",
    "SkillAnswerCorrectness",
    "skill_usage_expectations",
]
