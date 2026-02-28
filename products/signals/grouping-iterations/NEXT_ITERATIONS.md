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
  Most singletons are genuinely distinct, but some should merge:
  - Signals processed far apart in time never "see" each other.
  - Signals rejected by specificity from group X never try group Y.
  - Related singletons (e.g. 3 HubSpot connector issues) never get a chance to form their own group.
- The specificity gate is the primary filter (198 rejections),
  not a safety net. It's doing the matching step's job.

---

## Improvement areas

### Area 1: Post-processing (singleton consolidation)

**Priority: P1 — highest impact-to-risk ratio**

After all signals are processed, scan singletons for pairs/clusters that should merge.
This is purely additive — can't degrade existing groups.

#### 1a. Singleton-to-singleton consolidation

**What:** For each singleton, compute embedding similarity against other singletons.
If similarity is high, run the specificity check on the pair.
If it passes, merge into a new multi-signal group.

**Why:** Catches signals that were processed far apart and never appeared
as candidates for each other. Also catches cases where two signals were both
specificity-rejected from different groups but belong together.

**Example from 413 run:** 3 HubSpot singletons (junction tables, incremental sync, OAuth scope)
each got matched to different existing groups, rejected by specificity, became singletons.
They share an embedding neighborhood but never tried to merge with each other.

**Effort:** Moderate — reuses existing embedding cache and specificity check.
Complexity is O(singletons^2) for similarity, but can cap at top-K per singleton.

**Risk:** Low. Only touches singletons. Worst case: no merges pass specificity.

#### 1b. Singleton-to-small-group consolidation

**What:** After 1a, check if remaining singletons could join small groups (2-3 signals)
that were formed during 1a or during main processing.

**Effort:** Small increment over 1a.

**Risk:** Low — same specificity gate applies.

### Area 2: Matching step improvements

**Priority: P2 — addresses root cause but higher risk**

The matching step proposes bad matches based on keyword/embedding overlap.
The specificity gate catches them (198 rejections), but ideally the matching step
would propose fewer bad matches in the first place.

Previous conclusion still holds:
the bottleneck is the matching step, not the specificity prompt.
Loosening the specificity gate (v2, v3) re-introduced weak chaining.

#### 2a. Retry matching after specificity rejection

**What:** When specificity rejects a match to group X,
try the next-best candidate group Y instead of immediately creating a singleton.

**Implementation options:**

- Have matching LLM return ranked top 2-3 candidate groups.
  Run specificity on each in order until one passes.
- Or: re-run matching with group X excluded from candidates.

**Why:** Currently 198 signals are rejected from their first-choice group.
Some of those have a valid second-choice group that would pass specificity.

**Effort:** Moderate — needs matching prompt change (ranked output)
or an extra matching call per rejection.

**Risk:** Moderate. Adds 1-2 LLM calls for ~40% of signals.
Could slow processing. Marginal improvement per signal.

#### 2b. PR framing in the matching prompt

**What:** Move the "would this be one PR?" framing from the specificity gate
into the matching step itself.
The matching LLM would consider work-item scope before proposing a match,
not just signal relatedness.

**Why:** The matching step has the most context (new signal + candidates + group info).
Making it do the hard thinking means the specificity gate becomes a safety net.

**Effort:** Significant prompt rewrite.

**Risk:** Could make matching more conservative (more singletons).
Hard to tune — currently the separation of concerns (match vs. verify) is clean.

#### 2c. Negative examples in matching prompt

**What:** Add explicit "do NOT match" patterns targeting the exact failure mode:
signals that share a product keyword but describe different work items.

**Why:** The matching prompt currently only has positive guidance.
The LLM defaults to matching on surface similarity.

**Effort:** Prompt-only change, easy to test.

**Risk:** Might not generalize across signal sets. Brittle to maintain.

### Area 3: Candidate quality (search / filtering)

**Priority: P3 — supplementary, combine with other areas**

#### 3a. Reduce candidate noise before matching

**What:** Filter candidates before the matching LLM sees them:

- Lower candidate limit per query (e.g. 5 instead of 10)
- Cosine distance threshold to drop weak matches
- Deduplicate candidates across queries by report_id

**Why:** Many candidates are keyword-overlap noise.
Fewer, higher-quality candidates = fewer bad match proposals.

**Effort:** Simple deterministic code change.

**Risk:** Static thresholds don't generalize across signal types.
Different types have different embedding distances for "related."

#### 3b. Work-item-specific query generation

**What:** Generate search queries specific to the work item rather than the domain.
E.g. instead of "workflow metrics issues" → "NaN display bug in workflow metrics overview tab."

**Why:** Reduces keyword-overlap candidates at the source.

**Effort:** Prompt change to query generation.

**Risk:** More specific queries might miss legitimate matches.

---

## Recommended order

1. **1a** (singleton consolidation) — lowest risk, purely additive, catches clear wins
2. **2a** (retry after specificity rejection) — moderate effort, catches "wrong first choice" cases
3. **2c** (negative examples) — cheap prompt experiment, test in harness
4. **3a** (candidate filtering) — simple code change, can combine with any of the above
5. **2b** (PR framing in matching) — significant change, try only if 1-4 are insufficient

Approaches 1a and 2a can be developed independently and combined.
Approach 3a is a good complement to any matching improvement.

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

### Singletons that SHOULD merge (targets for consolidation)

- 3 HubSpot connector singletons (junction tables, incremental sync, OAuth scope)
  — different concerns within the same connector, could be one owner
- 2-3 MCP connection singletons (SSE handshake, tool discovery, OAuth registration)
  — different failure modes but same integration surface
- "Survey Slack interpolation" + existing "Survey Slack notification" group
  — same narrow scope, rejected because "3 distinct problems"

These are the cases singleton consolidation (1a) would catch.
