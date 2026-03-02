# Next iterations

## Current state (after 413-signal production run)

The `pr_specificity_and_group_aware` strategy is in production.
Results are strong — multi-signal groups are coherent with zero weak chaining detected.

### Key numbers (413-signal run)

| Metric                                   | Value                                 |
| ---------------------------------------- | ------------------------------------- |
| Reports                                  | 428 (354 singletons, 74 multi-signal) |
| Largest group                            | 9 signals (email verification)        |
| Specificity gate rejections              | 198 (56% of singletons)               |
| Matching LLM said "new" (had candidates) | 156 (44% of singletons)               |
| No candidates found at all               | 0                                     |
| Safety failures                          | 6 (all legitimate)                    |
| Weak-chained groups                      | 0                                     |
| Vague PR titles in groups                | 0                                     |

### What's working

- Multi-signal groups are high quality across the board.
  The 2-signal groups, 3-signal groups, and the 9-signal email group are all coherent.
- The specificity gate catches keyword-overlap matches effectively.
  The "different engineers" heuristic drives 56% of rejections (111/198) and is mostly correct.
- Safety gate catches all 6 injection/manipulation attempts.
- Sorting reports by signal_count surfaces the most impactful issues.

### What's not ideal

- 83% singleton rate.
  Most singletons are genuinely distinct — the specificity gate correctly rejects them.
  Signals DO find each other (0 signals had no candidates), but the matching step
  picks the wrong group first, specificity rejects, and the signal becomes a singleton
  without trying alternative candidates.
- The specificity gate is the primary filter (198 rejections),
  not a safety net. It's doing the matching step's job.

### Grouping granularity: task generation vs. knowledge base

Two valid grouping perspectives exist:

**Task generation** (current, for Twig):
signals grouped by actionable work item — one group = one PR / one set of tests.
3 HubSpot feature requests (junction tables, incremental sync, OAuth scope)
are 3 separate groups because they produce 3 different PRs.
Including all HubSpot issues in 1 report leads to a useless report for Twig.

**Knowledge base** (future, for UI/UX):
signals grouped by product area or owner — "HubSpot" label on all 3.
Useful for browsing, but not for task execution.
Implementable as a labeling/tagging layer on top of task-generation groups.
Not a priority for the Twig release.

We stay with task-generation grouping. Knowledge-base labeling is a separate concern.

---

## Improvement areas

### Area 1: Matching step improvements

**Priority: P1 — addresses root cause**

The matching step proposes bad matches based on keyword/embedding overlap.
The specificity gate catches them (198 rejections), but ideally the matching step
would propose fewer bad matches in the first place.

Previous conclusion still holds:
the bottleneck is the matching step, not the specificity prompt.
Loosening the specificity gate (v2, v3) re-introduced weak chaining.

#### 1a. Retry matching after specificity rejection

**What:** When specificity rejects a match to group X,
try the next-best candidate group Y instead of immediately creating a singleton.

**Implementation options:**

- Have matching LLM return ranked top 2-3 candidate groups.
  Run specificity on each in order until one passes.
- Or: re-run matching with group X excluded from candidates.

**Why:** Currently 198 signals are rejected from their first-choice group.
Some of those have a valid second-choice group that would pass specificity.
The search results already contain candidates from multiple groups —
we just need to try more than one.

**Effort:** Moderate — needs matching prompt change (ranked output)
or an extra matching call per rejection.

**Risk:** Moderate. Adds 1-2 LLM calls for ~40% of signals.
Could slow processing. Marginal improvement per signal.

#### 1b. PR framing in the matching prompt

**What:** Move the "would this be one PR?" framing from the specificity gate
into the matching step itself.
The matching LLM would consider work-item scope before proposing a match,
not just signal relatedness.

**Why:** The matching step has the most context (new signal + candidates + group info).
Making it do the hard thinking means the specificity gate becomes a safety net.

**Effort:** Significant prompt rewrite.

**Risk:** Could make matching more conservative (more singletons).
Hard to tune — currently the separation of concerns (match vs. verify) is clean.

#### 1c. Negative examples in matching prompt

**What:** Add explicit "do NOT match" patterns targeting the exact failure mode:
signals that share a product keyword but describe different work items.

**Why:** The matching prompt currently only has positive guidance.
The LLM defaults to matching on surface similarity.

**Effort:** Prompt-only change, easy to test.

**Risk:** Might not generalize across signal sets. Brittle to maintain.

### Area 2: Candidate quality (search / filtering)

**Priority: P2 — supplementary, combine with area 1**

#### 2a. Reduce candidate noise before matching

**What:** Filter candidates before the matching LLM sees them:

- Lower candidate limit per query (e.g. 5 instead of 10)
- Cosine distance threshold to drop weak matches
- Deduplicate candidates across queries by report_id

**Why:** Many candidates are keyword-overlap noise.
Fewer, higher-quality candidates = fewer bad match proposals.

**Effort:** Simple deterministic code change.

**Risk:** Static thresholds don't generalize across signal types.
Different types have different embedding distances for "related."

#### 2b. Work-item-specific query generation

**What:** Generate search queries specific to the work item rather than the domain.
E.g. instead of "workflow metrics issues" → "NaN display bug in workflow metrics overview tab."

**Why:** Reduces keyword-overlap candidates at the source.

**Effort:** Prompt change to query generation.

**Risk:** More specific queries might miss legitimate matches.

### Area 3: Knowledge-base labeling (future, not for Twig)

**Priority: P3 — separate concern, after Twig release**

A presentation layer that groups singletons by product area / owner for browsing.
Does not change task-generation grouping.

#### 3a. Label/tag singletons by product area

**What:** After task-generation grouping, run an additional pass
to assign labels (e.g. "HubSpot", "Session Replay", "Billing") to singletons.
Display as facets or filters in the UI, not as merged groups.

**Why:** Users browsing signal reports want to see "all HubSpot issues,"
even if each is a different work item.

**Effort:** Moderate — needs a labeling LLM call or keyword extraction,
plus UI work.

**Risk:** Low — purely additive, doesn't affect task-generation groups.

---

## Recommended order

1. **1a** (retry after specificity rejection) — addresses "wrong first choice," reuses existing search results
2. **1c** (negative examples) — cheap prompt experiment, test in harness
3. **2a** (candidate filtering) — simple code change, can combine with any of the above
4. **1b** (PR framing in matching) — significant change, try only if 1-3 are insufficient
5. **3a** (labeling) — after Twig release, separate workstream

---

## Observations from the 413-signal run

### Multi-signal groups are all coherent

Every group with 2+ signals passed manual review.
Top groups:

- [9] Fix email verification delivery and post-verification login flow
- [4] Fix Data Warehouse joins in funnels: null handling and person property breakdowns
- [4] Fix data warehouse join key selection and type validation for persons
- [4] Overhaul workflow metrics UI with better labels, controls, and layout
- [3] Add ingestion and UI for custom materialized properties from data warehouse
- ... (14 groups with 3+ signals, 60 groups with exactly 2)

### Specificity rejection reasons cluster around "different engineers"

111/198 rejections (56%) cite the "different engineers" heuristic.
Most are correct — the signals genuinely describe different work items.
A few borderline cases exist (e.g. survey Slack notification interpolation
vs. survey Slack notification triggering) but these are minority.

### Singleton keyword clusters (not under-grouped)

Large singleton clusters exist by keyword (19 dashboard, 18 workflow, 18 insight,
15 survey, 14 feature flag, 13 email, 13 session replay, 12 billing, 12 SDK).
These are NOT under-grouped — they are genuinely different issues within the same product area.
The specificity gate correctly identifies them as different work items.

### Signals DO find each other — processing order is not the bottleneck

Tracing the HubSpot chain confirmed signals discover each other via semantic search:

1. HubSpot 1 (00:15) "junction tables" → matched to data warehouse group → specificity rejected
2. HubSpot 2 (00:17) "incremental sync" → **found HubSpot 1's singleton** → specificity rejected ("two unrelated improvements")
3. HubSpot 3 (00:43) "OAuth scope" → **found HubSpot 2's singleton** → specificity rejected ("two unrelated improvements")

The singletons correctly remain separate under task-generation grouping —
they are genuinely different work items despite sharing the HubSpot domain.
This is knowledge-base labeling territory, not a grouping defect.
