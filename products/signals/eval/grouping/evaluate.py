"""
LLM-based evaluation of grouping results.

Two judges:
1. Group quality judge — evaluates each group for coherence, weak-chaining, misplaced signals
2. Signal placement judge — evaluates each signal's fit in its assigned group
"""

import json
import logging

from harness import GroupingDecision, GroupingResult, TestSignal, call_llm_standalone

logger = logging.getLogger(__name__)

EVAL_MODEL = "claude-sonnet-4-5"


# ---------------------------------------------------------------------------
# Helper: call LLM and parse JSON response (with retry)
# ---------------------------------------------------------------------------


async def _call_judge(system_prompt: str, user_prompt: str) -> dict:
    return await call_llm_standalone(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        validate=lambda text: json.loads(text),
        model=EVAL_MODEL,
        temperature=0.2,
        max_tokens=8192,
    )


# ---------------------------------------------------------------------------
# Judge 1: Group quality (coherence, weak-chaining, misplaced signals)
# ---------------------------------------------------------------------------

GROUPING_QUALITY_SYSTEM_PROMPT = """You are a strict evaluator of signal grouping quality. Your job is to find problems, not to praise.

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

## Scoring rubric

For multi-signal groups (2+):
- 5: One ticket/PR would cover all signals. Same specific problem or tightly coupled feature.
- 4: Strong core with 1 borderline signal that's related but could be a separate ticket.
- 3: Recognizable theme but 2+ signals would clearly be separate tickets.
- 2: Same broad product area but different work items. "Workflows" or "insights" is not enough.
- 1: No meaningful connection, or clear weak-chaining from end to end.

Be skeptical of any group with 5+ signals. Large groups are rarely coherent — the more signals, the higher the bar.

For single-signal groups: score as null (not applicable).

## Under-grouping detection

Singletons are a SAFE default. Only flag under-grouping when the connection is OBVIOUS and TIGHT:

> "Would these two signals unambiguously be the same Jira ticket or PR?"

If you would score a multi-signal group containing both signals at 3 or below, do NOT flag it as under-grouping.

## Response format

Respond with a JSON object. Keep assessments concise.

{
  "group_assessments": [
    {
      "group_id": "<report_id prefix>",
      "signal_count": <number>,
      "coherence_score": <1-5 or null for singletons>,
      "assessment": "<1-2 sentences. For 3+ signal groups, briefly trace any weak-chain drift>",
      "misplaced_signal_count": <number of signals that don't belong, 0 if all belong>
    }
  ],
  "undergrouping": [
    {"singleton_id": "<group_id>", "should_merge_with": "<group_id or 'other singleton: <id>'>", "reason": "<why>"}
  ],
  "overall_score": <1-5>,
  "overall_assessment": "<2-3 sentence summary focusing on what went WRONG>"
}"""


def _build_grouping_quality_prompt(result: GroupingResult) -> str:
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
                lines.append(
                    f"  - [id={sig.signal_id[:12]}] [{sig.source_product}/{sig.source_type}] {content_preview}"
                )
        lines.append("")

    return "\n".join(lines)


async def evaluate_grouping_quality(result: GroupingResult) -> dict:
    user_prompt = _build_grouping_quality_prompt(result)
    return await _call_judge(GROUPING_QUALITY_SYSTEM_PROMPT, user_prompt)


# ---------------------------------------------------------------------------
# Judge 2: Signal placement quality (per-signal fit assessment)
# ---------------------------------------------------------------------------

SIGNAL_PLACEMENT_SYSTEM_PROMPT = """You are evaluating individual signal placement decisions made by a grouping algorithm. Each signal is a bug report, feature request, or other product feedback from PostHog.

You will receive ALL groups with their signals, plus details of the algorithm's decision for each signal (NEW group vs MATCHED to existing, and its stated reason).

For EACH signal, evaluate:

1. **fit_score** (1-5): How well does this signal fit in its assigned group?
   - 5: Perfect fit — clearly the same specific issue/feature as the group
   - 4: Good fit — strongly related, minor stretch
   - 3: Borderline — related topic area but could be a separate work item
   - 2: Poor fit — only superficially related, different work items
   - 1: Wrong group — no meaningful connection
   - For singletons: how appropriate was it to keep this signal alone?
     - 5: Correctly alone — no other group is a good fit
     - 4: Probably alone — other groups are tangentially related at best
     - 3: Debatable — one group is somewhat related
     - 2: Likely should be grouped — one group is clearly related
     - 1: Definitely should be grouped — obvious match with an existing group

2. **correctly_placed** (true/false): Binary verdict — does this signal belong where it is?

3. **reasoning_quality** (1-5): Is the algorithm's stated reason for the decision accurate and specific?
   - 5: Precise, accurate reason that captures the real connection
   - 4: Correct but could be more specific
   - 3: Vague or partially correct
   - 2: Misleading — cites a superficial connection
   - 1: Wrong — the stated reason doesn't hold up

## Response format

{
  "signal_assessments": [
    {
      "signal_id": "<signal_id prefix>",
      "fit_score": <1-5>,
      "correctly_placed": <true/false>,
      "reasoning_quality": <1-5>,
      "assessment": "<1 sentence explaining your verdict>"
    }
  ]
}"""


def _build_signal_placement_prompt(
    result: GroupingResult,
    decisions: list[tuple[TestSignal, GroupingDecision]],
) -> str:
    signal_lookup: dict[str, TestSignal] = {s.signal_id: s for s in result.signals}

    lines = ["## All groups produced by the algorithm\n"]

    for group in sorted(result.groups.values(), key=lambda g: -len(g.signal_ids)):
        lines.append(f"### Group: {group.report_id[:12]}... ({len(group.signal_ids)} signals)")
        if group.title:
            lines.append(f"Title: {group.title}")
        for sid in group.signal_ids:
            sig = signal_lookup.get(sid)
            if sig:
                content_preview = sig.content[:300].replace("\n", " ")
                lines.append(
                    f"  - [id={sig.signal_id[:12]}] [{sig.source_product}/{sig.source_type}] {content_preview}"
                )
        lines.append("")

    lines.append("\n## Algorithm decisions (in processing order)\n")
    for signal, decision in decisions:
        content_preview = signal.content[:200].replace("\n", " ")
        action = "NEW group" if decision.is_new else f"MATCHED to group {decision.report_id[:12]}..."
        lines.append(f"- [id={signal.signal_id[:12]}] {action}")
        lines.append(f"  Reason: {decision.reason}")
        lines.append(f"  Content: {content_preview}")
        lines.append("")

    return "\n".join(lines)


async def evaluate_signal_placements(
    result: GroupingResult,
    decisions: list[tuple[TestSignal, GroupingDecision]],
) -> dict:
    user_prompt = _build_signal_placement_prompt(result, decisions)
    return await _call_judge(SIGNAL_PLACEMENT_SYSTEM_PROMPT, user_prompt)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_evaluation(evaluation: dict) -> str:
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

    return "\n".join(lines)
