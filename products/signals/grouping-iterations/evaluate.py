"""
LLM-based evaluation of grouping results.

Uses Claude to judge whether groups are coherent and compare against
original report assignments.
"""

import os
import json
import logging

import anthropic
from dotenv import find_dotenv, load_dotenv
from harness import GroupingResult, TestSignal

load_dotenv(find_dotenv(usecwd=True))

logger = logging.getLogger(__name__)

EVAL_MODEL = "claude-sonnet-4-5"

EVALUATION_SYSTEM_PROMPT = """You are a strict evaluator of signal grouping quality. Your job is to find problems, not to praise.

You will receive groups of signals that were clustered by a grouping algorithm. Each signal is a bug report, feature request, or other product feedback from a product analytics platform (PostHog).

## What makes a good group

A group is coherent when ALL signals share a **specific, concrete** problem or feature area — specific enough that ONE person or team would work on ALL of them together.

Good group examples:
- 3 signals all about the date picker being broken in insights → same component, same fix
- 4 signals about workflow email tracking metrics → same feature area, same team

Bad group examples (even if they seem related):
- "GDPR consent in NextJS" + "k8s probes for feature flag pods" → completely different problems, different teams, different codebases, even if both tangentially touch "feature flags"
- "Date picker UX" + "Reverse funnel analysis" + "Funnel time-to-convert histogram" → all "insights features" but actually 3 unrelated feature requests

## Weak-chaining detection (CRITICAL)

This is the #1 failure mode. For EVERY group with 3+ signals, you MUST perform this check:

1. Pick the FIRST and LAST signal added to the group
2. Ask: "Would these two signals EVER be in the same Jira ticket or PR?" If no → weak chaining.
3. Trace the chain: how did signal 1 connect to signal N? Write out each link.
4. If any link in the chain changes the topic (different component, different team, different problem type), flag it.

Example of weak chaining:
- Signal A: "GDPR consent not persisting in NextJS" (topic: consent/privacy)
- Signal B: "Next.js feature flag bootstrap issues" (topic: SDK/flags — linked to A via "NextJS")
- Signal C: ".NET SDK needs shared cache for flags" (topic: SDK caching — linked to B via "flags")
- Signal D: "K8s probes for feature-flag pods" (topic: infrastructure — linked to C via "flags")
→ A and D have NOTHING in common. This is weak chaining.

## Scoring rubric

For multi-signal groups (2+):
- 5: Every signal shares a specific problem/component. One person would work on all of them.
- 4: Strong core theme with 1 borderline signal.
- 3: Recognizable theme but some signals are stretches.
- 2: Loose connection only — signals are in the same broad product area but different problems.
- 1: No meaningful connection, or clear weak-chaining from end to end.

For single-signal groups: score as null (not applicable — they cannot be evaluated for coherence).

For the overall score, weight multi-signal groups heavily. A run that produces 10 singleton groups and 2 good multi-signal groups is NOT a 5/5 — it means the algorithm failed to find most connections.

## Response format

Respond with a JSON object:
{
  "group_assessments": [
    {
      "group_id": "<report_id prefix>",
      "signal_count": <number>,
      "coherence_score": <1-5 or null for singletons>,
      "assessment": "<1-2 sentence assessment>",
      "chain_trace": "<for 3+ signal groups: trace the connection chain from first to last signal, noting where topic shifts>",
      "misplaced_signals": ["<first ~80 chars of signal content if it doesn't belong>"],
      "suggested_splits": ["<description of sub-groups if applicable>"]
    }
  ],
  "merge_recommendations": [
    {"groups": ["<group_id>", "<group_id>"], "reason": "<why they should merge>"}
  ],
  "overall_score": <1-5>,
  "overall_assessment": "<2-3 sentence summary focusing on what went WRONG>",
  "weak_chaining_detected": <true/false>,
  "weak_chaining_examples": ["<specific chain trace showing the drift>"]
}"""


def _build_evaluation_prompt(result: GroupingResult) -> str:
    """Build the evaluation prompt from grouping results."""
    signal_lookup: dict[str, TestSignal] = {s.signal_id: s for s in result.signals}

    lines = ["Here are the groups produced by the algorithm:\n"]

    for group in sorted(result.groups.values(), key=lambda g: -len(g.signal_ids)):
        lines.append(f"## Group: {group.report_id[:12]}... ({len(group.signal_ids)} signals)")
        if group.title:
            lines.append(f"Title: {group.title}")

        for sid in group.signal_ids:
            sig = signal_lookup.get(sid)
            if sig:
                content_preview = sig.content[:300].replace("\n", " ")
                lines.append(f"  - [{sig.source_product}/{sig.source_type}] {content_preview}")
        lines.append("")

    # Add original grouping for comparison
    lines.append("\n---\nORIGINAL GROUPING (for comparison — also has quality issues, don't treat as ground truth):\n")
    original_groups: dict[str, list[str]] = {}
    for sig in result.signals:
        original_groups.setdefault(sig.original_report_id[:12], []).append(sig.signal_id)

    for orig_id, sids in sorted(original_groups.items(), key=lambda x: -len(x[1])):
        lines.append(f"## Original group: {orig_id}... ({len(sids)} signals)")
        for sid in sids:
            sig = signal_lookup.get(sid)
            if sig:
                content_preview = sig.content[:200].replace("\n", " ")
                lines.append(f"  - {content_preview}")
        lines.append("")

    return "\n".join(lines)


async def evaluate_grouping(result: GroupingResult) -> dict:
    """Run LLM evaluation of grouping results."""
    client = anthropic.AsyncAnthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=120.0,
    )

    user_prompt = _build_evaluation_prompt(result)

    response = await client.messages.create(
        model=EVAL_MODEL,
        system=EVALUATION_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": "{"},
        ],
        max_tokens=8192,
        temperature=0.2,
    )

    text = ""
    for block in reversed(response.content):
        if block.type == "text":
            text = block.text
            break

    text = "{" + text
    # Strip markdown fences if present
    stripped = text.strip()
    if stripped.startswith("```json") and stripped.endswith("```"):
        text = stripped[len("```json") : -len("```")].strip()
    elif stripped.startswith("```") and stripped.endswith("```"):
        text = stripped[len("```") : -len("```")].strip()

    return json.loads(text)


def format_evaluation(evaluation: dict, result: GroupingResult) -> str:
    """Format evaluation results as a readable string."""
    signal_lookup: dict[str, TestSignal] = {s.signal_id: s for s in result.signals}
    lines: list[str] = []

    lines.append("EVALUATION REPORT")
    lines.append("")
    lines.append(f"Overall Score: {evaluation.get('overall_score', '?')}/5")
    lines.append(f"Assessment: {evaluation.get('overall_assessment', 'N/A')}")
    lines.append("")

    if evaluation.get("weak_chaining_detected"):
        lines.append("WEAK CHAINING DETECTED:")
        for example in evaluation.get("weak_chaining_examples", []):
            lines.append(f"  - {example}")
        lines.append("")

    lines.append("Group Assessments:")
    for ga in evaluation.get("group_assessments", []):
        score = ga.get("coherence_score")
        score_str = f"{score}/5" if score is not None else "n/a"
        lines.append(f"\n  {ga['group_id']} ({ga.get('signal_count', '?')} signals, coherence: {score_str})")
        lines.append(f"    {ga.get('assessment', 'N/A')}")
        if ga.get("chain_trace"):
            lines.append(f"    Chain: {ga['chain_trace']}")
        if ga.get("misplaced_signals"):
            lines.append("    Misplaced signals:")
            for sid in ga["misplaced_signals"]:
                sig = signal_lookup.get(sid)
                if sig:
                    lines.append(f"      - {sig.content[:80].replace(chr(10), ' ')}")
                else:
                    lines.append(f"      - {sid}")
        if ga.get("suggested_splits"):
            lines.append("    Suggested splits:")
            for split in ga["suggested_splits"]:
                lines.append(f"      - {split}")

    if evaluation.get("merge_recommendations"):
        lines.append("\nMerge Recommendations:")
        for mr in evaluation["merge_recommendations"]:
            lines.append(f"  - Merge {mr['groups']}: {mr['reason']}")

    return "\n".join(lines)
