# Plan: Implement `pr_specificity_and_group_aware` strategy in production

## Context

The Signals product groups incoming signals into `SignalReport`s via embedding similarity + LLM matching.
The current strategy suffers from **weak-chaining** -- signal A matches B (shared keyword), B matches C (different keyword), resulting in A and C in the same group despite being unrelated.

The `pr_specificity_and_group_aware` harness strategy scored best in offline testing (3.78-4.50 weighted coherence, 0-1 weak-chain groups, 1-2 misplaced signals vs the baseline's 1.97-2.65, 2-3, 13-18).
This plan ports its three innovations into production.

## What changes

### 1. Group-aware matching prompt (replaces current signal-to-signal matching)
- Each search candidate annotated with its group title + size
- New "Discovery Strength" section showing multi-query agreement per group
- System prompt: "Match to a GROUP's theme, not just an individual signal"

### 2. PR-specificity gate (new step after matching)
- When LLM proposes matching to existing group, a verification LLM call asks: "Write a PR title covering ALL signals in this group + the new one. Is it specific enough?"
- If too broad ("Fix various PostHog AI issues") -> reject, create new group
- If specific -> confirm match

### 3. Title feedback loop
- When specificity confirms a match, the synthesized PR title becomes `SignalReport.title`
- Future signals see this improved title in the group-aware matching prompt

## Modified `_process_one_signal()` flow

```
1. Embed signal + fetch type examples (parallel)                -- UNCHANGED
2. Generate 1-3 search queries via LLM                          -- UNCHANGED
3. Embed queries (parallel)                                      -- UNCHANGED
4. Semantic search per query (parallel)                          -- UNCHANGED
4.5 Fetch report contexts (titles, counts) from Postgres         -- NEW
5. Group-aware LLM match (with group titles, sizes, discovery)   -- MODIFIED
5.5 PR-specificity verification (if matched to existing)         -- NEW
    -> If rejected: convert to NewReportMatch
    -> If confirmed: set updated_title for feedback loop
6. Assign + emit (with optional title update)                    -- MODIFIED
7. Wait for ClickHouse                                           -- UNCHANGED
8. If promoted -> start summary workflow                         -- UNCHANGED
```

## Files modified

### `products/signals/backend/temporal/types.py`
- Added `ReportContext` dataclass (report_id, title, signal_count)
- Added `SpecificityMetadata` dataclass (pr_title, specific_enough, reason)
- Added `specificity: Optional[SpecificityMetadata] = None` to `MatchedMetadata`
- Added `specificity_rejection: Optional[SpecificityMetadata] = None` to `NoMatchMetadata`

### `products/signals/backend/temporal/grouping.py` (bulk of changes)

**New imports:** `defaultdict`, `ReportContext`, `SignalData`, `SpecificityMetadata`

**Prompts:**
- Replaced `MATCHING_SYSTEM_PROMPT` with group-aware version (from harness `GROUP_AWARE_MATCHING_SYSTEM_PROMPT`)
- Added `SPECIFICITY_CHECK_SYSTEM_PROMPT` (from harness `pr_specificity_strategy.py`)
- Added `SpecificityResult` Pydantic model
- Added `MAX_SIGNALS_IN_SPECIFICITY_CONTEXT = 8`

**Functions:**
- Replaced `_build_matching_prompt()` -- new signature adds `report_contexts: dict[str, ReportContext]`, builds discovery strength + group annotations
- Added `_build_specificity_prompt()` -- takes signal info + group signals (up to 8), asks LLM to write a PR title
- Updated `match_signal_to_report()` -- passes report_contexts through
- Updated `MatchSignalToReportInput` -- added `report_contexts` field

**New activity: `fetch_report_contexts_activity`**
- Input: `FetchReportContextsInput(report_ids: list[str])`
- Output: `FetchReportContextsOutput(contexts: dict[str, ReportContext])`
- Simple Postgres query: `SignalReport.objects.filter(id__in=...).values_list("id", "title", "signal_count")`

**New activity: `verify_match_specificity_activity`**
- Input: `VerifyMatchSpecificityInput(team_id, report_id, report_title, new_signal_description, new_signal_source_product, new_signal_source_type)`
- Output: `VerifyMatchSpecificityOutput(pr_title, specific_enough, reason)`
- Fetches signals for report from ClickHouse (same query pattern as `fetch_signals_for_report_activity` in summary.py) + runs specificity LLM call

**Modified `assign_and_emit_signal_activity`:**
- Added `updated_title: Optional[str] = None` to `AssignAndEmitSignalInput`
- When `updated_title` is set and match is `ExistingReportMatch`, also updates `report.title`

**Modified `_process_one_signal()`:**
- After step 4 (semantic search): collects unique report_ids, calls `fetch_report_contexts_activity`
- Passes `report_contexts` to `match_signal_to_report_activity`
- After step 5 (matching): if `ExistingReportMatch`, calls `verify_match_specificity_activity`
  - If confirmed: sets `updated_title = specificity_result.pr_title`, adds specificity to match_metadata
  - If rejected: replaces match_result with `NewReportMatch(title=description[:75], summary="Split from group: {title}")` with rejection context in `NoMatchMetadata`
- Passes `updated_title` to `assign_and_emit_signal_activity`

### `products/signals/backend/temporal/__init__.py`
- Imported and registered `fetch_report_contexts_activity` and `verify_match_specificity_activity` in ACTIVITIES list

## Design clarifications

- **Group annotations in matching prompt**: Only title + size per candidate, NOT signal descriptions. Keeps the matching prompt lightweight (avoids the over-conservative behavior seen in `group_aware_strategy`). Full signal descriptions are only used in the specificity check step.
- **Specificity gate**: One LLM call, not two. The prompt asks the LLM to write a PR title AND judge specificity in a single response `{pr_title, specific_enough, reason}`. Writing the title IS the evaluation — the LLM must try to unify the signals into one PR, and the quality of the result reveals whether they belong together. Two calls would add latency without benefit.
- **Import vs copy**: Prompts are copied into production code (not imported from harness). The harness has incompatible top-level imports (no Django/Temporal). This is the same approach the harness uses in reverse.
