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
from collections import Counter
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
    "GenericUpdateSetsFields",
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


def _seed(output: dict | None) -> dict | None:
    seed = (output or {}).get("seed")
    return seed if isinstance(seed, dict) else None


# The by-key lookup accepts these aliases and normalizes them onto `key`, and the log
# records what the agent sent rather than what the tool normalized it to.
_FLAG_KEY_FIELDS = ("key", "flagKey", "flag_key", "feature_flag_key", "featureFlagKey")


def _targets_seeded_flag(call: ToolCall, seed: dict | None) -> bool:
    """Did this call name the flag the case seeded?

    Each case runs in a team that already holds the demo project's own flags, and the
    prompts name a flag by key while the write tools take a numeric id. The same tool
    call on a different flag is a different answer, so the tool name alone cannot say
    the agent did what was asked. A call that names no flag this can check, such as a
    search, still counts: what that call contributes to a case is the tool itself.
    """
    if seed is None:
        return True
    flag_id = seed.get("feature_flag_id")
    if flag_id is not None and "id" in call.input:
        return str(call.input["id"]) == str(flag_id)
    key = seed.get("feature_flag_key")
    if key is None:
        return True
    named = [call.input[field] for field in _FLAG_KEY_FIELDS if field in call.input]
    return key in named if named else True


def _on_seeded_flag(calls: list[ToolCall], seed: dict | None) -> list[ToolCall]:
    return [call for call in calls if _targets_seeded_flag(call, seed)]


def _tools(spec: dict) -> list[str]:
    raw = spec.get("tools")
    return [tool for tool in raw if isinstance(tool, str)] if isinstance(raw, list) else []


class CalledExpectedTool(Scorer):
    """Binary: did the agent successfully call one of ``expected.tools`` on the seeded flag?

    One instance serves every case, because what varies between cases is exactly the
    tool a competent agent should reach for. The flag has to match too: the same
    lifecycle call on one of the demo project's own flags is the mis-resolution these
    cases exist to catch, not a pass.
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

        seed = _seed(output)
        called = sorted({tool for tool in tools if _on_seeded_flag(_successful(parser, tool), seed)})
        if called:
            return Score(name=self._name(), score=1.0, metadata={"called": called})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "expected_any_of": sorted(tools),
                "called_on_another_flag": sorted({tool for tool in tools if _successful(parser, tool)}),
            },
        )


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


def _same_text(written: Any, asked: Any) -> bool:
    """Compare what the agent wrote against what the prompt asked for.

    Case and surrounding whitespace are the agent's to choose; the words are not.
    """
    if isinstance(written, str) and isinstance(asked, str):
        return written.strip().casefold() == asked.strip().casefold()
    return bool(written == asked)


class GenericUpdateSetsFields(Scorer):
    """Binary: did the generic updates carry every ``expected.fields`` value?

    The check above passes by inaction, because an update carrying nothing omits every
    forbidden field too. This is the positive half: the edit the user asked for has to
    be in a body somewhere. `name` holds the description on this model, so an agent
    that hears "rename" and writes the new key into `name` fails here while looking
    right to every other row on the case.

    The fields may arrive across more than one update, because splitting the rename
    from the description is chatty rather than wrong.
    """

    def _name(self) -> str:
        return "generic_update_sets_fields"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _spec(expected, self._name())
        raw = spec.get("fields") if spec else None
        fields = raw if isinstance(raw, dict) and raw else None
        if not fields:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()}.fields on case"})
        parser = _parser(output)
        if not parser:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        writes = _on_seeded_flag(_successful(parser, GENERIC_UPDATE_TOOL), _seed(output))
        written = {field: [call.input[field] for call in writes if field in call.input] for field in fields}
        missing = sorted(
            field for field, values in written.items() if not any(_same_text(value, fields[field]) for value in values)
        )
        return Score(
            name=self._name(),
            score=0.0 if missing else 1.0,
            metadata={
                "not_written_as_asked": missing,
                "written": {field: values for field, values in written.items() if values},
            },
        )


class CreatedFlagWithTags(Scorer):
    """Binary: did the flag the case asked for land, carrying at least one tag?

    The project requires a tag, so a create with none is rejected. This passes only
    when the agent ends up with that flag created, whether it tagged the first attempt
    or recovered from the rejection. A tagged create under some other key is a
    different flag, so it does not count.
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

        seed = _seed(output)
        attempts = parser.get_tool_calls(CREATE_TOOL)
        for call in attempts:
            if call.is_error or not _targets_seeded_flag(call, seed):
                continue
            tags = call.input.get("tags")
            if isinstance(tags, list) and any(isinstance(tag, str) and tag.strip() for tag in tags):
                return Score(name=self._name(), score=1.0, metadata={"tags": tags, "attempts": len(attempts)})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": "No successful create of the case's flag carried a tag", "attempts": len(attempts)},
        )


def _groups(filters: Any) -> list[dict]:
    if not isinstance(filters, dict):
        return []
    groups = filters.get("groups")
    return [group for group in groups if isinstance(group, dict)] if isinstance(groups, list) else []


def _variants(filters: Any) -> list[str]:
    """Every variant, whole and in order.

    Whole, because a variant compared by its percentage alone survives a rewrite that
    drops its name. In order, because the list decides which users land in which
    variant. Only the keys inside one variant are sorted, which an agent is free to
    reorder.
    """
    if not isinstance(filters, dict):
        return []
    multivariate = filters.get("multivariate")
    variants = multivariate.get("variants") if isinstance(multivariate, dict) else None
    if not isinstance(variants, list):
        return []
    return [json.dumps(variant, sort_keys=True) for variant in variants]


def _canonical_group(group: dict) -> str:
    """One release condition as a comparable string.

    The whole condition, because a percentage read apart from the properties it serves
    cannot tell a rollout change from two conditions trading percentages, and a
    condition read as properties plus percentage hides a group-level variant override.
    The properties inside a condition are sorted because they AND together, and keys
    are sorted because an agent that rewrites the definition may emit them in any order.
    """
    properties = group.get("properties")
    canonical: dict[str, Any] = {key: value for key, value in group.items() if key != "properties"}
    canonical["properties"] = (
        sorted(json.dumps(prop, sort_keys=True) for prop in properties) if isinstance(properties, list) else properties
    )
    return json.dumps(canonical, sort_keys=True)


class PreservedUnrelatedConfig(Scorer):
    """Binary: did the rollout edit move one number and keep everything else?

    Sending `filters` replaces the whole object, so an agent that writes the new
    percentage without merging the current definition silently drops the other release
    condition, the variants and the payloads. Compares whole release conditions against
    the ones the seed declared, so a write that moves the number onto the wrong
    condition fails, while a rewrite that only reorders what it read still passes.
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
        source = seed.get("rollout_from_percentage")
        target = seed.get("rollout_to_percentage")

        before_groups = _groups(before)
        after_groups = _groups(after)
        moved = [
            {**group, "rollout_percentage": target}
            for group in before_groups
            if group.get("rollout_percentage") == source
        ]
        pinned = [group for group in before_groups if group.get("rollout_percentage") != source]
        # Counted over every condition at once, so two of them that traded percentages
        # cannot cover for each other.
        missing = Counter(_canonical_group(group) for group in [*moved, *pinned]) - Counter(
            _canonical_group(group) for group in after_groups
        )

        checks = {
            "moved_the_target_group": not any(_canonical_group(group) in missing for group in moved),
            "kept_the_other_conditions": not any(_canonical_group(group) in missing for group in pinned),
            "kept_every_condition": len(after_groups) == len(before_groups),
            "kept_the_variants": _variants(after) == _variants(before),
            "kept_the_payloads": (after.get("payloads") if isinstance(after, dict) else None) == before.get("payloads"),
        }
        failed = sorted(name for name, ok in checks.items() if not ok)
        return Score(
            name=self._name(),
            score=0.0 if failed else 1.0,
            metadata={
                "failed_checks": failed,
                "conditions_not_written": sorted(missing.elements()),
                "written_filters": after,
            },
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
