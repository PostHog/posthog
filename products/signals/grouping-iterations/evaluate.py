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
4. Trace the chain: how did signal 1 connect to signal N? Identify where topic shifts happen.
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

For the overall score, prioritize PRECISION over RECALL:
- A correct singleton is neutral (score: 0 impact). Many singletons is fine.
- A misplaced signal in a group is bad (-1 impact per misplaced signal).
- A weak-chained group (coherence ≤ 2) is very bad (-2 impact per group).
- A large weak-chained group (5+) is worse than a small one.
- Under-grouping is a minor issue compared to over-grouping. Only penalize when connections are unambiguous (same ticket/PR).

## Under-grouping detection

Singletons are a SAFE default — a signal that stays alone is not a failure. It just means the algorithm hasn't seen a strong enough match yet. Only flag under-grouping when the connection is OBVIOUS and TIGHT:

> "Would these two signals unambiguously be the same Jira ticket or PR?"

Apply the SAME strictness as the coherence rubric. "Same product area" or "same SDK/framework" is NOT enough. If you would score a multi-signal group containing both signals at 3 or below, do NOT flag it as under-grouping.

Examples of what IS under-grouping (flag these):
- Two bug reports about the same LLM trace viewer rendering issue → same fix
- Two feature requests for the same funnel histogram metric → same ticket

Examples of what is NOT under-grouping (do NOT flag):
- "GDPR consent in Next.js" + "Next.js feature flag refresh" → different problems, different fixes
- "push notification support" + "Microsoft Teams integration" → different channels, different APIs
- "AI JS error in SQL Editor" + "AI invalid insight payloads" → different components, different fixes

Report genuine misses in the "undergrouping" array.

## Response format

Respond with a JSON object. Keep assessments concise — include chain reasoning inline when relevant, but do NOT repeat signal contents verbatim.

{
  "group_assessments": [
    {
      "group_id": "<report_id prefix>",
      "signal_count": <number>,
      "coherence_score": <1-5 or null for singletons>,
      "assessment": "<1-2 sentences. For 3+ signal groups with weak chaining, briefly trace the drift (e.g. 'chains from metrics UI → email tracking → push notifications via workflows keyword')>",
      "misplaced_signal_count": <number of signals that don't belong in this group, 0 if all belong>
    }
  ],
  "undergrouping": [
    {"singleton_id": "<group_id of singleton>", "should_merge_with": "<group_id or 'other singleton: <id>'>", "reason": "<why>"}
  ],
  "merge_recommendations": [
    {"groups": ["<group_id>", "<group_id>"], "reason": "<why they should merge>"}
  ],
  "overall_score": <1-5>,
  "overall_assessment": "<2-3 sentence summary focusing on what went WRONG>"
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


def compute_summary_metrics(evaluation: dict, result: GroupingResult) -> dict:
    """Derive deterministic comparison metrics from evaluation results."""
    group_assessments = evaluation.get("group_assessments", [])
    multi_signal = [ga for ga in group_assessments if ga.get("coherence_score") is not None]

    total_weighted = sum(ga["coherence_score"] * ga["signal_count"] for ga in multi_signal)
    total_signals_in_groups = sum(ga["signal_count"] for ga in multi_signal)
    weighted_coherence = total_weighted / total_signals_in_groups if total_signals_in_groups else 0

    weak_chain_count = sum(1 for ga in multi_signal if ga["coherence_score"] <= 2)
    total_misplaced = sum(ga.get("misplaced_signal_count", 0) for ga in group_assessments)

    group_count = len(result.groups)
    singleton_count = sum(1 for g in result.groups.values() if len(g.signal_ids) == 1)

    undergrouping_count = len(evaluation.get("undergrouping", []))

    return {
        "overall_score": evaluation.get("overall_score", 0),
        "weighted_coherence": round(weighted_coherence, 2),
        "group_count": group_count,
        "multi_signal_groups": group_count - singleton_count,
        "singletons": singleton_count,
        "weak_chain_groups": weak_chain_count,
        "total_misplaced": total_misplaced,
        "undergrouping_misses": undergrouping_count,
    }


def format_metrics(metrics: dict) -> str:
    """Format summary metrics as a compact comparison-friendly string."""
    lines = [
        "METRICS (for cross-run comparison)",
        "",
        f"  Overall score:       {metrics['overall_score']}/5",
        f"  Weighted coherence:  {metrics['weighted_coherence']}/5.0",
        f"  Groups:              {metrics['group_count']} ({metrics['multi_signal_groups']} multi-signal, {metrics['singletons']} singletons)",
        f"  Weak-chain groups:   {metrics['weak_chain_groups']}",
        f"  Misplaced signals:   {metrics['total_misplaced']}",
        f"  Under-grouping:      {metrics['undergrouping_misses']} missed merges",
    ]
    return "\n".join(lines)


def format_evaluation(evaluation: dict) -> str:
    """Format evaluation results as a readable string."""
    lines: list[str] = []

    lines.append("EVALUATION REPORT")
    lines.append("")
    lines.append(f"Overall Score: {evaluation.get('overall_score', '?')}/5")
    lines.append(f"Assessment: {evaluation.get('overall_assessment', 'N/A')}")
    lines.append("")

    lines.append("Group Assessments:")
    for ga in evaluation.get("group_assessments", []):
        score = ga.get("coherence_score")
        score_str = f"{score}/5" if score is not None else "n/a"
        misplaced = ga.get("misplaced_signal_count", 0)
        misplaced_str = f", {misplaced} misplaced" if misplaced else ""
        lines.append(
            f"\n  {ga['group_id']} ({ga.get('signal_count', '?')} signals, coherence: {score_str}{misplaced_str})"
        )
        lines.append(f"    {ga.get('assessment', 'N/A')}")

    if evaluation.get("undergrouping"):
        lines.append("\nUnder-grouping (missed merges):")
        for ug in evaluation["undergrouping"]:
            lines.append(f"  - {ug['singleton_id']} should merge with {ug['should_merge_with']}: {ug['reason']}")

    if evaluation.get("merge_recommendations"):
        lines.append("\nMerge Recommendations:")
        for mr in evaluation["merge_recommendations"]:
            lines.append(f"  - Merge {mr['groups']}: {mr['reason']}")

    return "\n".join(lines)
