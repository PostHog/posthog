"""Scorers for the feature-flag lifecycle evals.

Every scorer reads its per-case parameters from ``expected`` under its own
``_name()``, the convention ``products/posthog_ai/evals/cli_mcp/scorers.py`` uses,
and returns ``score=None`` when its key is absent so a case it does not apply to
does not drag the rollup down.

The deterministic ones read the agent's tool calls, not the database. What went
wrong in a bad run is which tool the agent picked and what it put in the payload, so
that is what these grade. A flag left in the right state by the wrong write — a
generic PATCH that replaced `filters` on its way to flipping `active` — is the exact
failure the lifecycle tools exist to prevent, and final state cannot see it.
"""

from __future__ import annotations

import json
from typing import Any

from products.posthog_ai.eval_harness.log_parser import LogParser, ToolCall
from products.posthog_ai.eval_harness.scorers import BINARY_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

__all__ = [
    "EXPLAINED_KEY_REUSE_QUESTION",
    "EXPLAINED_TAG_REQUIREMENT_QUESTION",
    "GENERIC_UPDATE_TOOL",
    "REFUSED_WITHOUT_BLAMING_QUESTION",
    "STALE_IS_NOT_SAFE_TO_REMOVE_QUESTION",
    "AvoidedTool",
    "CalledExpectedTool",
    "CreatedFlagWithTags",
    "FinalMessageJudge",
    "GenericUpdateOmitsFields",
    "PreservedUnrelatedConfig",
]

GENERIC_UPDATE_TOOL = "update-feature-flag"
CREATE_TOOL = "create-feature-flag"


def _spec(expected: dict | None, scorer_name: str) -> dict | None:
    if not isinstance(expected, dict):
        return None
    spec = expected.get(scorer_name)
    return spec if isinstance(spec, dict) else None


def _parser(output: dict | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser.cached(raw_log, initial_prompt=output.get("prompt", "") or "")


def _successful(parser: LogParser, name: str) -> list[ToolCall]:
    return [call for call in parser.get_tool_calls(name) if not call.is_error]


def _tools(spec: dict) -> list[str]:
    raw = spec.get("tools")
    return [tool for tool in raw if isinstance(tool, str)] if isinstance(raw, list) else []


class CalledExpectedTool(Scorer):
    """Binary: did the agent successfully call one of ``expected.tools``?

    One instance serves every case, because what varies between cases is exactly the
    tool a competent agent should reach for.
    """

    def _name(self) -> str:
        return "called_expected_tool"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _spec(expected, self._name())
        tools = _tools(spec) if spec else []
        if not tools:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()}.tools on case"})
        parser = _parser(output)
        if not parser:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        called = sorted({tool for tool in tools if _successful(parser, tool)})
        if called:
            return Score(name=self._name(), score=1.0, metadata={"called": called})
        return Score(name=self._name(), score=0.0, metadata={"expected_any_of": sorted(tools)})


class AvoidedTool(Scorer):
    """Binary: did the agent avoid successfully calling any of ``expected.tools``?

    Failed attempts pass. The agent is free to try a tool and be refused; what this
    grades is whether the write landed.
    """

    def _name(self) -> str:
        return "avoided_tool"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _spec(expected, self._name())
        tools = _tools(spec) if spec else []
        if not tools:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()}.tools on case"})
        parser = _parser(output)
        if not parser:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        called = sorted({tool for tool in tools if _successful(parser, tool)})
        if called:
            return Score(name=self._name(), score=0.0, metadata={"called": called})
        return Score(name=self._name(), score=1.0, metadata={"forbidden": sorted(tools)})


class GenericUpdateOmitsFields(Scorer):
    """Binary: did every successful generic update leave ``expected.fields`` out?

    Two failures share this shape. A metadata edit that also sends `filters` replaces
    the whole targeting object, so a condition someone added between the read and the
    write is gone. A state change sent as `active` or `archived` here does the same
    thing on the way to a flip that `feature-flag-enable` / `-disable` would have made
    on its own, with no body at all.
    """

    def _name(self) -> str:
        return "generic_update_omits_fields"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _spec(expected, self._name())
        raw = spec.get("fields") if spec else None
        fields = [field for field in raw if isinstance(field, str)] if isinstance(raw, list) else []
        if not fields:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()}.fields on case"})
        parser = _parser(output)
        if not parser:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        sent = sorted(
            {field for call in _successful(parser, GENERIC_UPDATE_TOOL) for field in fields if field in call.input}
        )
        if sent:
            return Score(name=self._name(), score=0.0, metadata={"sent_via_generic_update": sent})
        return Score(name=self._name(), score=1.0, metadata={"forbidden_fields": sorted(fields)})


class CreatedFlagWithTags(Scorer):
    """Binary: did a successful create land, carrying at least one tag?

    The project requires a tag, so a create with none is rejected. This passes only
    when the agent ends up with the flag created, whether it tagged the first attempt
    or recovered from the rejection.
    """

    def _name(self) -> str:
        return "created_flag_with_tags"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _spec(expected, self._name())
        if not spec:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        parser = _parser(output)
        if not parser:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        attempts = parser.get_tool_calls(CREATE_TOOL)
        for call in attempts:
            if call.is_error:
                continue
            tags = call.input.get("tags")
            if isinstance(tags, list) and any(isinstance(tag, str) and tag.strip() for tag in tags):
                return Score(name=self._name(), score=1.0, metadata={"tags": tags, "attempts": len(attempts)})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": "No successful create carried a tag", "attempts": len(attempts)},
        )


def _groups(filters: Any) -> list[dict]:
    if not isinstance(filters, dict):
        return []
    groups = filters.get("groups")
    return [group for group in groups if isinstance(group, dict)] if isinstance(groups, list) else []


def _variant_percentages(filters: Any) -> dict[str, Any]:
    if not isinstance(filters, dict):
        return {}
    multivariate = filters.get("multivariate")
    variants = multivariate.get("variants") if isinstance(multivariate, dict) else None
    if not isinstance(variants, list):
        return {}
    return {
        variant["key"]: variant.get("rollout_percentage")
        for variant in variants
        if isinstance(variant, dict) and isinstance(variant.get("key"), str)
    }


def _property_filters(filters: Any) -> list[str]:
    """Each release condition's property list, canonicalized and order-insensitive.

    Sorted keys and a sorted outer list, because an agent that rewrites the definition
    is free to reorder both without changing who the flag serves.
    """
    return sorted(
        json.dumps(group["properties"], sort_keys=True) for group in _groups(filters) if group.get("properties")
    )


class PreservedUnrelatedConfig(Scorer):
    """Binary: did the rollout edit move one number and keep everything else?

    Sending `filters` replaces the whole object, so an agent that writes the new
    percentage without merging the current definition silently drops the other release
    condition, the variants and the payloads. Checks the shape the seed declared rather
    than a byte-for-byte match, so an equivalent rewrite still passes.
    """

    def _name(self) -> str:
        return "preserved_unrelated_config"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _spec(expected, self._name())
        if not spec:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        seed = (output or {}).get("seed")
        if not isinstance(seed, dict) or not isinstance(seed.get("initial_filters"), dict):
            return Score(name=self._name(), score=0.0, metadata={"reason": "Case seed carries no initial_filters"})
        parser = _parser(output)
        if not parser:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        writes = [call for call in _successful(parser, GENERIC_UPDATE_TOOL) if "filters" in call.input]
        if not writes:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No successful update sent filters"})

        before = seed["initial_filters"]
        after = writes[-1].input["filters"]
        target = seed.get("rollout_to_percentage")
        pinned = [
            group.get("rollout_percentage")
            for group in _groups(before)
            if group.get("rollout_percentage") != seed.get("rollout_from_percentage")
        ]

        after_percentages = [group.get("rollout_percentage") for group in _groups(after)]
        checks = {
            "moved_the_target_group": target in after_percentages,
            "kept_the_other_conditions": all(percentage in after_percentages for percentage in pinned),
            "kept_every_condition": len(_groups(after)) == len(_groups(before)),
            "kept_the_property_filters": _property_filters(after) == _property_filters(before),
            "kept_the_variants": _variant_percentages(after) == _variant_percentages(before),
            "kept_the_payloads": (after.get("payloads") if isinstance(after, dict) else None) == before.get("payloads"),
        }
        failed = sorted(name for name, ok in checks.items() if not ok)
        return Score(
            name=self._name(),
            score=0.0 if failed else 1.0,
            metadata={"failed_checks": failed, "written_filters": after},
        )


class FinalMessageJudge(JudgedScorer):
    """Judge one yes/no question about the agent's final message.

    Four cases each need a different question asked of the same input, so the question
    is the only thing that varies. `name` doubles as the `expected` key that opts a
    case in, and the question text carries what a `yes` requires.
    """

    def __init__(self, *, name: str, question: str, **kwargs):
        super().__init__(
            name=name,
            prompt_template=f"{question}\n\n<message>{{{{output.last_message}}}}</message>\n\nAnswer `yes` or `no`.",
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        if not _spec(expected, self._name()):
            return Score(name=self._name(), score=None, metadata={"reason": "Not applicable to this case"})
        if not output or not output.get("last_message"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final message"})
        return {"output": {"last_message": output["last_message"]}}


EXPLAINED_KEY_REUSE_QUESTION = (
    "A user asked an assistant to create a feature flag, and the key they named already belonged to "
    "an existing flag. Does the message below tell the user that a flag with that key already "
    "existed, and say what the assistant did about it (used the existing flag, or asked which they "
    "wanted)? A message that reports creating a new flag, or that stops at an error without naming "
    "the existing flag, is a no."
)

STALE_IS_NOT_SAFE_TO_REMOVE_QUESTION = (
    "A user asked an assistant whether a feature flag is stale and what evidence there is. The flag "
    "has not been evaluated for months, and another active flag depends on it. Does the message "
    "below report the staleness as one signal rather than proof, and name at least one thing that "
    "removal would still have to account for (the dependent flag, a linked experiment or survey, "
    "code references, or the limits of evaluation data)? A message that concludes the flag is safe "
    "to remove, or that it can be deleted, is a no."
)

REFUSED_WITHOUT_BLAMING_QUESTION = (
    "A user asked an assistant to change a feature flag. The organization allows the assistant to "
    "read data but not to change it, so the write was refused. Does the message below tell the user "
    "the change did not happen, and give the reason as a permission the assistant does not have "
    "rather than as a broken flag, a missing flag, or an unexplained failure? Naming who can lift "
    "the restriction, or what the user can do instead, also counts as yes. A message that claims the "
    "change was made is a no."
)

EXPLAINED_TAG_REQUIREMENT_QUESTION = (
    "A user asked an assistant to create a feature flag. The project requires every new flag to "
    "carry at least one tag, which the user did not mention. Does the message below tell the user "
    "that the project requires a tag on new flags, and say which tag the flag now carries? A message "
    "that reports the flag as created without mentioning the tag requirement is a no, and so is one "
    "that stops at the error."
)
