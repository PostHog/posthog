# Next iterations: fixing the matching step

## Context

After testing `pr_specificity_and_group_aware` v1/v2/v3,
the conclusion is that the specificity gate is not the bottleneck.
The matching step proposes bad matches based on keyword overlap
(e.g. "workflow metrics", "Next.js", "flags"),
and any loosening of the specificity gate re-exposes them.

The fix needs to happen upstream — in how matches are proposed,
not in how they're verified.

## Approaches (ordered by effort-to-improvement ratio)

### 1. Negative examples in the matching prompt

**What:** Add explicit "do NOT match" patterns to `GROUP_AWARE_MATCHING_SYSTEM_PROMPT`.
Target the exact failure mode: signals that share a product keyword but describe different work items.

**Why it might work:** The matching prompt currently only has positive guidance ("match if related").
The LLM defaults to matching on surface similarity because it's not told not to.

**Effort:** Prompt-only change, easy to test in harness.

**Risk:** Might not generalize if the failure modes shift with different signal sets.

### 2. Tighten the matching prompt with PR framing

**What:** Move the "would this be one PR?" framing from the specificity gate
into the matching step itself.
The matching LLM would need to consider work-item scope _before_ proposing a match,
not just signal relatedness.

**Why it might work:** The matching step has the most context (new signal + candidates + group info).
Making it do the hard thinking means the specificity gate becomes a safety net, not the primary filter.

**Effort:** Significant prompt rewrite for the matching step.

**Risk:** Doubles prompt complexity. Could make matching more conservative (more singletons).

### 3. Two-phase matching in one call

**What:** Combine match proposal + PR-title synthesis into a single LLM call.
Instead of: match → separate specificity check,
do: "propose a candidate AND write a PR title" in one shot.

**Why it might work:** Gives the LLM full context at decision time.
The current split means the specificity gate can't see _why_ the match was proposed.

**Effort:** Moderate — new prompt structure, but reuses existing building blocks.

**Risk:** Single complex prompt might degrade at both tasks.
Saves one LLM call per signal though.

### 4. Reduce candidate noise before matching

**What:** Filter candidates before the matching LLM sees them:

- Lower candidate limit (e.g. 5 per query instead of 10)
- Cosine distance threshold to drop weak matches
- Deduplicate candidates across queries

**Why it might work:** Many candidates are keyword-overlap noise.
Fewer, higher-quality candidates = fewer bad match proposals.

**Effort:** Simple, deterministic code change.

**Risk:** Static thresholds don't generalize well across signal types
(different types have different embedding distances for "related").

### 5. Change query generation strategy

**What:** Generate queries specific to the _work item_ rather than the _domain_.
E.g. instead of "workflow metrics issues" → "NaN display bug in workflow metrics overview tab."

**Why it might work:** Reduces keyword-overlap candidates at the source.
More specific queries = more specific candidates.

**Effort:** Prompt change to query generation step.

**Risk:** Harder to control — query generation is already LLM-driven.
More specific queries might miss legitimate matches.

## Recommended order

1. Try **approach 1** (negative examples) — cheapest test, targets exact failure mode
2. If insufficient, try **approach 2** (PR framing in matching) — addresses root cause
3. **Approach 3** is worth trying if 1+2 don't work — structural change
4. **Approaches 4 and 5** are supplementary — can combine with any of the above
