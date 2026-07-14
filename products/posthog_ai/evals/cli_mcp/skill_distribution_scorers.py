from __future__ import annotations

import re
import json
from dataclasses import dataclass
from typing import cast

from braintrust import Score
from braintrust_core.score import Scorer

from products.posthog_ai.eval_harness.harness.cli import SkillDelivery
from products.posthog_ai.eval_harness.log_parser import EXEC_TOOL_NAME, LogParser, ToolCall, normalize_tool_name

_BUNDLED_SKILL_PATH_MARKERS = (
    "/scripts/plugins/posthog/skills/",
    "/root/.claude/skills/",
    "/root/.agents/skills/",
    "~/.claude/skills/",
    "~/.agents/skills/",
)


@dataclass(frozen=True)
class _SkillLoad:
    position: int
    call_id: str
    matched_via: str


def skill_distribution_expectations(
    skill: str, downstream_tools: list[str], skill_delivery: SkillDelivery
) -> dict[str, dict[str, object]]:
    expectations: dict[str, dict[str, object]] = {
        "expected_skill_loaded": {"skill": skill, "delivery": skill_delivery},
        "skill_loaded_before_tool": {
            "skill": skill,
            "delivery": skill_delivery,
            "tools": downstream_tools,
        },
    }
    if skill_delivery == "exec":
        expectations.update(
            {
                "skill_search_first": {},
                "expected_skill_discovered": {"skill": skill},
                "no_bundled_skill_bypass": {},
            }
        )
    else:
        expectations["no_exec_skill_bypass"] = {}
    return expectations


def _expected_spec(expected: dict[str, object] | None, scorer_name: str) -> dict[str, object] | None:
    if not isinstance(expected, dict) or scorer_name not in expected:
        return None
    spec = expected[scorer_name]
    return cast(dict[str, object], spec) if isinstance(spec, dict) else None


def _parser(output: dict[str, object] | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not isinstance(raw_log, str) or not raw_log:
        return None
    prompt = output.get("prompt")
    return LogParser.cached(raw_log, initial_prompt=prompt if isinstance(prompt, str) else "")


def _exec_command(call: ToolCall) -> tuple[str, str]:
    if call.is_exec_unwrapped or normalize_tool_name(call.raw_name) != EXEC_TOOL_NAME:
        return ("", "")
    command = call.input.get("command")
    if not isinstance(command, str):
        return ("", "")
    verb, _, rest = command.strip().partition(" ")
    return (verb.lower(), rest.strip())


def _successful_exec_calls(parser: LogParser) -> list[ToolCall]:
    return [
        call
        for call in parser.get_tool_calls()
        if not call.is_error and normalize_tool_name(call.raw_name) == EXEC_TOOL_NAME
    ]


def _is_skill_search(call: ToolCall) -> bool:
    verb, rest = _exec_command(call)
    return verb == "learn" and (rest == "-s" or rest.startswith("-s "))


def _skill_search_calls(parser: LogParser) -> list[ToolCall]:
    return [call for call in _successful_exec_calls(parser) if _is_skill_search(call)]


def _qualified_skill(skill: str) -> str:
    return f"posthog:{skill}"


def _output_mentions_skill(output: str, qualified_skill: str) -> bool:
    return re.search(rf"(?<![a-zA-Z0-9_-]){re.escape(qualified_skill)}(?![a-zA-Z0-9_-])", output) is not None


def _exec_skill_load_calls(parser: LogParser, qualified_skill: str) -> list[ToolCall]:
    return [call for call in _successful_exec_calls(parser) if _exec_command(call) == ("learn", qualified_skill)]


def _bundled_skill_loads(parser: LogParser, skill: str) -> list[_SkillLoad]:
    loads = [
        _SkillLoad(position=call.position, call_id=call.call_id, matched_via="skill_tool")
        for call in parser.get_skill_calls(skill)
        if not call.is_error
    ]

    skill_file_ref = f"{skill}/skill.md".lower()
    for call in parser.get_tool_calls():
        if call.is_error:
            continue
        reference = f"{call.name}\n{json.dumps(call.input, default=str)}".lower()
        if skill_file_ref in reference:
            loads.append(_SkillLoad(position=call.position, call_id=call.call_id, matched_via="skill_file_reference"))

    return sorted(loads, key=lambda load: load.position)


def _skill_loads(parser: LogParser, skill: str, delivery: SkillDelivery) -> list[_SkillLoad]:
    if delivery == "bundled":
        return _bundled_skill_loads(parser, skill)
    return [
        _SkillLoad(position=call.position, call_id=call.call_id, matched_via="exec_learn")
        for call in _exec_skill_load_calls(parser, _qualified_skill(skill))
    ]


def _skill_and_delivery(spec: dict[str, object]) -> tuple[str, SkillDelivery] | None:
    skill = spec.get("skill")
    delivery = spec.get("delivery")
    if not isinstance(skill, str) or not skill or delivery not in ("bundled", "exec"):
        return None
    return skill, cast(SkillDelivery, delivery)


def _is_exec_skill_command(call: ToolCall) -> bool:
    verb, rest = _exec_command(call)
    return verb == "learn" and (
        rest == "skills"
        or rest == "-s"
        or rest.startswith("-s ")
        or rest.startswith("posthog:")
        or rest.startswith("project:")
    )


class SkillSearchFirst(Scorer):
    def _name(self) -> str:
        return "skill_search_first"

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

        searches = _skill_search_calls(parser)
        if not searches:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No successful learn -s command"})

        first_search = searches[0]
        earlier_non_learning = [
            call
            for call in _successful_exec_calls(parser)
            if _exec_command(call)[0] != "learn" and call.position <= first_search.position
        ]
        if earlier_non_learning:
            first = earlier_non_learning[0]
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "A non-learning PostHog command ran before skill search",
                    "call_id": first.call_id,
                    "tool": first.name,
                },
            )
        return Score(name=self._name(), score=1.0, metadata={"call_id": first_search.call_id})


class ExpectedSkillDiscovered(Scorer):
    def _name(self) -> str:
        return "expected_skill_discovered"

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
        if not isinstance(skill, str) or not skill:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Expected skill is missing"})
        parser = _parser(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        qualified_skill = _qualified_skill(skill)
        for call in _skill_search_calls(parser):
            if _output_mentions_skill(call.output, qualified_skill):
                return Score(name=self._name(), score=1.0, metadata={"skill": qualified_skill, "call_id": call.call_id})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "Skill search did not return the expected qualified name",
                "skill": qualified_skill,
            },
        )


class ExpectedSkillLoaded(Scorer):
    def _name(self) -> str:
        return "expected_skill_loaded"

    def _run_eval_sync(
        self,
        output: dict[str, object] | None,
        expected: dict[str, object] | None = None,
        **kwargs: object,
    ) -> Score:
        spec = _expected_spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Scorer does not apply"})
        skill_spec = _skill_and_delivery(spec)
        if skill_spec is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Invalid scorer expectation"})
        skill, delivery = skill_spec
        parser = _parser(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        loads = _skill_loads(parser, skill, delivery)
        if delivery == "bundled" and loads:
            load = loads[0]
            return Score(
                name=self._name(),
                score=1.0,
                metadata={
                    "skill": skill,
                    "delivery": delivery,
                    "call_id": load.call_id,
                    "matched_via": load.matched_via,
                },
            )

        qualified_skill = _qualified_skill(skill)
        matching_searches = [
            call for call in _skill_search_calls(parser) if _output_mentions_skill(call.output, qualified_skill)
        ]
        if any(search.position < load.position for search in matching_searches for load in loads):
            load = next(load for load in loads if any(search.position < load.position for search in matching_searches))
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"skill": qualified_skill, "delivery": delivery, "call_id": load.call_id},
            )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": (
                    "Expected bundled skill was not loaded"
                    if delivery == "bundled"
                    else "Expected skill was not loaded by exact qualified name after discovery"
                ),
                "skill": skill,
                "delivery": delivery,
            },
        )


class SkillLoadedBeforeTool(Scorer):
    def _name(self) -> str:
        return "skill_loaded_before_tool"

    def _run_eval_sync(
        self,
        output: dict[str, object] | None,
        expected: dict[str, object] | None = None,
        **kwargs: object,
    ) -> Score:
        spec = _expected_spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Scorer does not apply"})
        skill_spec = _skill_and_delivery(spec)
        tools = spec.get("tools")
        if skill_spec is None or not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
            return Score(name=self._name(), score=0.0, metadata={"reason": "Invalid scorer expectation"})
        skill, delivery = skill_spec
        parser = _parser(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        loads = _skill_loads(parser, skill, delivery)
        downstream_calls = [call for call in parser.get_tool_calls() if not call.is_error and call.name in tools]
        for load in loads:
            for downstream in downstream_calls:
                if load.position < downstream.position:
                    return Score(
                        name=self._name(),
                        score=1.0,
                        metadata={
                            "skill": skill,
                            "delivery": delivery,
                            "tool": downstream.name,
                            "call_id": downstream.call_id,
                            "matched_via": load.matched_via,
                        },
                    )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "No expected downstream tool ran after the skill was loaded",
                "skill": skill,
                "delivery": delivery,
                "tools": tools,
            },
        )


class NoBundledSkillBypass(Scorer):
    def _name(self) -> str:
        return "no_bundled_skill_bypass"

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

        native_skill_calls = [call for call in parser.get_skill_calls() if not call.is_error]
        if native_skill_calls:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "A native Skill tool bypassed exec distribution",
                    "skill": native_skill_calls[0].name,
                },
            )

        for call in parser.get_tool_calls():
            if call.is_error:
                continue
            serialized_input = json.dumps(call.input, sort_keys=True).lower()
            if "skill.md" in serialized_input and any(
                marker in serialized_input for marker in _BUNDLED_SKILL_PATH_MARKERS
            ):
                return Score(
                    name=self._name(),
                    score=0.0,
                    metadata={"reason": "A bundled SKILL.md was read directly", "call_id": call.call_id},
                )

        return Score(name=self._name(), score=1.0)


class NoExecSkillBypass(Scorer):
    def _name(self) -> str:
        return "no_exec_skill_bypass"

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

        bypasses = [call for call in _successful_exec_calls(parser) if _is_exec_skill_command(call)]
        if bypasses:
            verb, rest = _exec_command(bypasses[0])
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "An exec skill command bypassed bundled delivery",
                    "call_id": bypasses[0].call_id,
                    "command": f"{verb} {rest}".strip(),
                },
            )
        return Score(name=self._name(), score=1.0)


__all__ = [
    "ExpectedSkillDiscovered",
    "ExpectedSkillLoaded",
    "NoBundledSkillBypass",
    "NoExecSkillBypass",
    "SkillLoadedBeforeTool",
    "SkillSearchFirst",
    "skill_distribution_expectations",
]
