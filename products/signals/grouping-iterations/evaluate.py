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

A group should map to roughly ONE actionable work item. The test is:

> "Could you write ONE Jira ticket or ONE pull request that addresses every signal in this group?"

If the answer is no, the group is too broad — even if all signals are in the same product area.

CRITICAL: "Same product/feature area" is NOT enough. A team may own 20 different work items. Each group should be ONE of those items, not all 20.

Good group examples:
- 3 bug reports about the date picker dropdown closing unexpectedly → one fix
- 2 signals about funnel Time to Convert needing percentile and median options → one feature

Bad group examples (even if they feel related):
- "workflow metrics NaN bug" + "push notification support" + "Microsoft Teams integration" → all "workflows" but 3 completely separate work items that would be 3 separate tickets
- "email open rate tracking" + "workflow chart improvements" + "node view metrics overhaul" → all "workflow metrics" but 3 different pieces of work
- "AI deleting dashboard content" + "AI JS error in SQL Editor" → both "PostHog AI bugs" but different components, different fixes, different PRs

## Weak-chaining detection (CRITICAL)

This is the #1 failure mode. For EVERY group with 3+ signals, you MUST perform this check:

1. Pick the FIRST and LAST signal added to the group
2. Ask: "Would these two signals EVER be in the same Jira ticket or PR?" If no → weak chaining.
3. Also check ALL PAIRS — pick any two signals that are NOT adjacent in the chain. Are they related without the bridging signals?
4. Trace the chain: how did signal 1 connect to signal N? Write out each link.
5. If any link in the chain changes the topic (different component, different fix, different feature), flag it.

Example of weak chaining through a shared product area:
- Signal A: "Workflow metrics overview tab needs redesign" (topic: metrics UI)
- Signal B: "Track email open rate with workflows" (topic: email analytics)
- Signal C: "Native push notification support for workflows" (topic: new channel)
- Signal D: "Support Microsoft Graph API for Teams" (topic: third-party integration)
→ All are "workflows" but A and D have nothing in common. These are 4 separate work items.

Example of weak chaining through a shared keyword:
- Signal A: "GDPR consent not persisting in NextJS" (topic: consent/privacy)
- Signal B: "Next.js feature flag bootstrap issues" (topic: SDK/flags — linked to A via "NextJS")
- Signal C: "Nuxt SSR flag hydration bug" (topic: different framework entirely — linked to B via "flags")
→ A and C have nothing in common. Different frameworks, different problems.

## Scoring rubric

For multi-signal groups (2+):
- 5: One ticket/PR would cover all signals. Same specific problem or tightly coupled feature.
- 4: Strong core with 1 borderline signal that's related but could be a separate ticket.
- 3: Recognizable theme but 2+ signals would clearly be separate tickets.
- 2: Same broad product area but different work items. "Workflows" or "insights" is not enough.
- 1: No meaningful connection, or clear weak-chaining from end to end.

Be skeptical of any group with 5+ signals. Large groups are rarely coherent — the more signals, the higher the bar.

For single-signal groups: score as null (not applicable).

For the overall score: weight multi-signal groups by size. A large group (5+) with weak chaining is worse than a small group (2-3) with weak chaining because it means the algorithm drifted further.

## Under-grouping detection

Over-grouping (weak chaining) is bad, but under-grouping is also a failure. For EVERY singleton group, ask:

> "Is there another group (or another singleton) that this signal clearly belongs with?"

If yes, the algorithm missed a real connection. Common patterns:
- Two singletons that are obviously the same issue (e.g., two different reports of the same bug)
- A singleton that clearly belongs in an existing multi-signal group (e.g., a "date picker" singleton when there's already a "date picker improvements" group)
- Related singletons that should have formed a group together

A run with many avoidable singletons is a sign the algorithm is too conservative — it fails to find real connections.

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
