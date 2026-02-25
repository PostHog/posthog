"""
LLM-based evaluation of grouping results.

Uses Claude to judge whether groups are coherent and compare against
original report assignments.
"""

import json
import os

import anthropic
from dotenv import find_dotenv, load_dotenv

from harness import GroupingResult, TestSignal

load_dotenv(find_dotenv(usecwd=True))

EVAL_MODEL = "claude-sonnet-4-5"

EVALUATION_SYSTEM_PROMPT = """You are an expert evaluator of signal grouping quality for a product analytics platform.

You will receive groups of signals that were clustered by a grouping algorithm. Each signal is a bug report, feature request, or other product feedback item.

Your job is to evaluate the QUALITY of the grouping:

1. **Group Coherence** (per group): Are the signals in each group genuinely related by a common root cause, feature area, or user journey? Or are some signals weakly connected / unrelated?

2. **Split Recommendations**: Should any group be split into multiple sub-groups? If so, which signals should go where?

3. **Merge Recommendations**: Should any groups be merged because they're about the same underlying issue?

4. **Overall Quality Score** (1-5):
   - 1: Mostly wrong — signals are randomly grouped
   - 2: Poor — many signals in wrong groups, significant weak-chaining
   - 3: Acceptable — core groups are right but some noise/misplacements
   - 4: Good — most groups are coherent with minor issues
   - 5: Excellent — all groups are tightly coherent

Be especially critical about "weak-chaining" — where signal A relates to B, and B relates to C, but A and C are actually about completely different things. This is the main failure mode we're trying to detect.

Respond with a JSON object:
{
  "group_assessments": [
    {
      "group_id": "<report_id prefix>",
      "coherence_score": <1-5>,
      "assessment": "<1-2 sentence assessment>",
      "misplaced_signals": ["<signal_id if any signal doesn't belong>"],
      "suggested_splits": ["<description of sub-groups if applicable>"]
    }
  ],
  "merge_recommendations": [
    {"groups": ["<group_id>", "<group_id>"], "reason": "<why they should merge>"}
  ],
  "overall_score": <1-5>,
  "overall_assessment": "<2-3 sentence summary of grouping quality>",
  "weak_chaining_detected": <true/false>,
  "weak_chaining_examples": ["<description of weak-chain if detected>"]
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
    lines.append("\n---\nORIGINAL GROUPING (for comparison):\n")
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


def print_evaluation(evaluation: dict, result: GroupingResult):
    """Print evaluation results in a readable format."""
    signal_lookup: dict[str, TestSignal] = {s.signal_id: s for s in result.signals}

    print(f"\n{'='*60}")
    print("EVALUATION REPORT")
    print(f"{'='*60}\n")

    print(f"Overall Score: {evaluation.get('overall_score', '?')}/5")
    print(f"Assessment: {evaluation.get('overall_assessment', 'N/A')}\n")

    if evaluation.get("weak_chaining_detected"):
        print("WEAK CHAINING DETECTED:")
        for example in evaluation.get("weak_chaining_examples", []):
            print(f"  - {example}")
        print()

    print("Group Assessments:")
    for ga in evaluation.get("group_assessments", []):
        print(f"\n  {ga['group_id']} (coherence: {ga.get('coherence_score', '?')}/5)")
        print(f"    {ga.get('assessment', 'N/A')}")
        if ga.get("misplaced_signals"):
            print("    Misplaced signals:")
            for sid in ga["misplaced_signals"]:
                sig = signal_lookup.get(sid)
                if sig:
                    print(f"      - {sig.content[:80].replace(chr(10), ' ')}")
                else:
                    print(f"      - {sid}")
        if ga.get("suggested_splits"):
            print("    Suggested splits:")
            for split in ga["suggested_splits"]:
                print(f"      - {split}")

    if evaluation.get("merge_recommendations"):
        print("\nMerge Recommendations:")
        for mr in evaluation["merge_recommendations"]:
            print(f"  - Merge {mr['groups']}: {mr['reason']}")

    print()
