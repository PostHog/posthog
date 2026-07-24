"""Frozen ``remediation-coherence-v2`` report-shuffling oracle."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path

from products.signals.backend.grouping_replay.cache import append_jsonl, read_jsonl_cache
from products.signals.backend.grouping_replay.engine import Signal
from products.signals.backend.grouping_replay.providers import OracleProvider

MAX_DESCRIPTION_CHARS = 1200
PROMPT_VERSION = "remediation-coherence-v2"


@dataclass(frozen=True)
class _EvidenceGroup:
    id: str
    members: list[Signal]


@dataclass(frozen=True)
class OraclePrompt:
    text: str
    left_groups: dict[str, list[str]]
    right_groups: dict[str, list[str]]


@dataclass(frozen=True)
class OracleDecision:
    action: str
    selected_left: list[str]
    selected_right: list[str]
    audit: dict[str, object]


def _compact_description(value: str) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= MAX_DESCRIPTION_CHARS else normalized[:MAX_DESCRIPTION_CHARS] + "..."


def _group_members(side: str, members: list[Signal], trigger_signal_id: str) -> list[_EvidenceGroup]:
    grouped: dict[tuple[str, str, str, bool], list[Signal]] = {}
    for member in members:
        key = (member.product, member.source_type, member.content, member.id == trigger_signal_id)
        grouped.setdefault(key, []).append(member)
    values = [grouped[key] for key in sorted(grouped)]
    values.sort(key=lambda group: (-len(group), group[0].content))
    return [_EvidenceGroup(id=f"{side}{index}", members=group) for index, group in enumerate(values, start=1)]


def _render_inventory(
    title: str,
    groups: list[_EvidenceGroup],
    proposed: set[str],
    trigger_signal_id: str,
) -> str:
    lines = [f"{title}: {sum(len(group.members) for group in groups)} MEMBERS IN {len(groups)} ATOMIC EVIDENCE GROUPS"]
    for group in groups:
        exemplar = group.members[0]
        selected = sum(member.id in proposed for member in group.members)
        trigger = any(member.id == trigger_signal_id for member in group.members)
        description = json.dumps(_compact_description(exemplar.content), ensure_ascii=False, separators=(",", ":"))
        lines.append(
            f"{group.id} COUNT={len(group.members)} SOURCE={exemplar.product}/{exemplar.source_type} "
            f"TRIGGER={str(trigger).lower()} PROPOSED_SELECTED={selected}/{len(group.members)} "
            f"DESCRIPTION={description}"
        )
    return "\n".join(lines)


def build_prompt(
    *,
    trigger_signal_id: str,
    trigger_score: float,
    left_members: list[Signal],
    right_members: list[Signal],
    proposed_left: list[str],
    proposed_right: list[str],
) -> OraclePrompt:
    left_groups = _group_members("L", left_members, trigger_signal_id)
    right_groups = _group_members("R", right_members, trigger_signal_id)
    left_text = _render_inventory(
        "LEFT REPORT (CURRENT JOIN WINNER)", left_groups, set(proposed_left), trigger_signal_id
    )
    right_text = _render_inventory("RIGHT REPORT (RUNNER-UP)", right_groups, set(proposed_right), trigger_signal_id)
    text = f"""You are the final semantic oracle for one report-shuffling proposal.

One new signal has already been joined into the LEFT report. The learned join model also found the RIGHT report plausible, with runner-up score {trigger_score:.6f}. A neural shuffler then proposed one cross-report member mask. PROPOSED_SELECTED=x/y on each evidence group shows how many members the neural mask selected.

Reports consolidate evidence about an underlying product problem. The unit of grouping is a shared investigation or remediation target, not one symptom, exception, call site, component, narrowly phrased pull request, or currently known fix.

Group signals when they are reasonably likely to be different manifestations of the same defect, causal mechanism, affected user journey, or remediation effort. One underlying problem may appear through different symptoms, signal types, exception classes, code paths, or components. It may initially appear to require several changes. If investigating the signals together would help an engineer discover and resolve their shared cause, they belong together.

Separate signals only when there is affirmative evidence that they are independent problems whose causes, resolution, or validation would be handled separately. Shared product area, generic symptom, sentiment, exception class, or vocabulary alone is not sufficient to group them. However, uncertainty about the exact root cause is not itself a reason to split: do not require proof of a shared cause when it is a credible explanation supported by the evidence.

Duplicate reports are costly because they fragment evidence and can cause duplicate investigations or pull requests. Do not split one underlying issue merely because each manifestation could receive its own narrow issue title. When both interpretations remain plausible, prefer preserving a useful shared investigation over creating near-duplicate reports, while still rejecting combinations that would obscure genuinely independent problems.

Judge the complete inventories, not just the trigger signal.

Choose exactly one action:
- accept: the neural mask identifies one remediation-coherent cross-report set and applying it is better than leaving the reports unchanged.
- reject: no safe useful cross-report operation is justified, or the neural proposal would mix distinct concerns. This leaves the post-join reports unchanged.
- alternative: one different remediation-coherent cross-report member mask is clearly better. Return the LEFT and RIGHT atomic evidence group IDs for one shared investigation or remediation target. Selecting a group selects every member represented by that group. The alternative must include at least one group from each side. It may select all groups on one or both sides.

Do not return multiple components. If several unrelated shared problems exist, choose alternative only when one is clearly the most useful immediate consolidation; otherwise reject. Infer shared causes reasonably from the supplied evidence, but do not invent unsupported connections merely to reduce report count.

Return only JSON:
{{
  "action": "accept" | "reject" | "alternative",
  "left_groups": ["L1"],
  "right_groups": ["R2"],
  "reason": "brief semantic boundary explanation",
  "confidence": "high" | "medium" | "low"
}}

For accept or reject, left_groups and right_groups must be empty arrays.

{left_text}

{right_text}"""
    return OraclePrompt(
        text=text,
        left_groups={group.id: [member.id for member in group.members] for group in left_groups},
        right_groups={group.id: [member.id for member in group.members] for group in right_groups},
    )


def parse_json_text(text: str) -> dict[str, object]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response contains no JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("response JSON must be an object")
    return value


def _string_array(value: dict[str, object], key: str) -> list[str]:
    items = value.get(key)
    if not isinstance(items, list):
        raise ValueError(f"{key} must be an array")
    if not all(isinstance(item, str) for item in items):
        raise ValueError(f"{key} entries must be strings")
    return [str(item) for item in items]


def _expand_groups(groups: list[str], inventory: dict[str, list[str]], side: str) -> list[str]:
    seen: set[str] = set()
    selected: list[str] = []
    for group in groups:
        if group in seen:
            raise ValueError(f"{side} group {group} is repeated")
        seen.add(group)
        if group not in inventory:
            raise ValueError(f"unknown {side} group {group}")
        selected.extend(inventory[group])
    return selected


def parse_response(
    value: dict[str, object],
    *,
    model: str,
    prompt: OraclePrompt,
    proposed_left: list[str],
    proposed_right: list[str],
) -> OracleDecision:
    raw_action = value.get("action")
    if not isinstance(raw_action, str):
        raise ValueError("action must be a string")
    action = raw_action.lower()
    reason = value.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be a non-empty string")
    confidence = value.get("confidence")
    if confidence not in {"high", "medium", "low"}:
        raise ValueError("confidence must be high, medium, or low")
    left_groups = _string_array(value, "left_groups")
    right_groups = _string_array(value, "right_groups")

    if action == "accept":
        if left_groups or right_groups:
            raise ValueError("accept must not return alternative groups")
        if not proposed_left or not proposed_right:
            raise ValueError("cannot accept a one-sided neural mask")
        selected_left, selected_right = list(proposed_left), list(proposed_right)
    elif action == "reject":
        if left_groups or right_groups:
            raise ValueError("reject must not return alternative groups")
        selected_left, selected_right = [], []
    elif action == "alternative":
        if not left_groups or not right_groups:
            raise ValueError("alternative must select at least one group from each side")
        selected_left = _expand_groups(left_groups, prompt.left_groups, "left")
        selected_right = _expand_groups(right_groups, prompt.right_groups, "right")
    else:
        raise ValueError(f"unknown action {action}")

    audit: dict[str, object] = {
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "action": action,
        "reason": reason,
        "confidence": confidence,
        "selected_left": selected_left,
        "selected_right": selected_right,
    }
    return OracleDecision(
        action=action,
        selected_left=selected_left,
        selected_right=selected_right,
        audit=audit,
    )


class OracleService:
    """Run and append-only cache the exact frozen oracle interaction."""

    def __init__(self, provider: OracleProvider | None, cache_dir: Path, model: str, max_tokens: int = 6000) -> None:
        self.provider = provider
        self.cache_path = cache_dir / "oracle-responses.jsonl"
        self.model = model
        self.max_tokens = max_tokens
        self.calls = 0
        self.cache_hits = 0

    async def _one_shot(self, prompt: str) -> str:
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        cache = read_jsonl_cache(self.cache_path, ("prompt_sha256", "model", "prompt_version"))
        cached = cache.get((prompt_hash, self.model, PROMPT_VERSION))
        if cached is not None:
            self.cache_hits += 1
            return str(cached["response"])
        if self.provider is None:
            raise ValueError("oracle-on requires an oracle provider or a matching cached response")
        response = await self.provider.complete(model=self.model, prompt=prompt, max_tokens=self.max_tokens)
        self.calls += 1
        append_jsonl(
            self.cache_path,
            {
                "prompt_sha256": prompt_hash,
                "model": self.model,
                "prompt_version": PROMPT_VERSION,
                "response": response,
            },
        )
        return response

    async def judge(
        self,
        *,
        trigger_signal_id: str,
        trigger_score: float,
        left_members: list[Signal],
        right_members: list[Signal],
        proposed_left: list[str],
        proposed_right: list[str],
    ) -> OracleDecision:
        prompt = build_prompt(
            trigger_signal_id=trigger_signal_id,
            trigger_score=trigger_score,
            left_members=left_members,
            right_members=right_members,
            proposed_left=proposed_left,
            proposed_right=proposed_right,
        )
        response = await self._one_shot(prompt.text)
        try:
            return parse_response(
                parse_json_text(response),
                model=self.model,
                prompt=prompt,
                proposed_left=proposed_left,
                proposed_right=proposed_right,
            )
        except Exception as error:
            correction = (
                f"{prompt.text}\n\nYour previous response failed validation. Return a corrected JSON object only.\n"
                f"VALIDATOR ERROR: {error}\nPREVIOUS RESPONSE: {response}"
            )
            corrected = await self._one_shot(correction)
            return parse_response(
                parse_json_text(corrected),
                model=self.model,
                prompt=prompt,
                proposed_left=proposed_left,
                proposed_right=proposed_right,
            )
