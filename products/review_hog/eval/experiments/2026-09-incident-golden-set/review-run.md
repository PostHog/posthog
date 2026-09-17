# Sandbox usage — incident golden-set review run (2026-09-02)

Operational log for the golden-set experiment: how many sandbox agents ReviewHog spawned
reviewing the 34 resurrected PRs. Companion to the judging results in this directory.

## TLDR

| Metric                                                               | Value                                   |
| -------------------------------------------------------------------- | --------------------------------------- |
| Reviews run                                                          | 34 (33 completed, 1 terminated mid-run) |
| **Total sandboxes spawned**                                          | **~546**                                |
| Review-stage turns (perspectives + blind-spot), completed reviews    | 138                                     |
| Validation turns (1 per candidate finding), completed reviews        | 245                                     |
| Terminated review (INC-921): sandbox chunking + partial review turns | 163                                     |
| Median / mean sandboxes per completed review                         | 10 / ~11.6                              |
| Cheapest review                                                      | 2 (single perspective, zero findings)   |
| Most expensive completed review                                      | 36 (INC-931: 4 chunks)                  |
| Share of all sandboxes consumed by the terminated INC-921 run        | ~30%                                    |

## How sandboxes are counted

Each sandbox is one agent turn spawned through the tasks infrastructure. Per review:

- **Review stage** = (perspectives selected per chunk, summed) + 1 blind-spot turn per chunk.
  Read directly from the pipeline's in-flight `reviewing done/total` counters.
- **Validation stage** = 1 turn per candidate finding. Verified: the `validating` totals matched
  the final candidate count on every review observed mid-run (8 of 8 checked).
- Chunking, perspective selection, and dedup ran as direct LLM calls (no sandbox) for every PR
  except INC-921, whose 446-file diff exceeded the one-shot chunking gate and used a sandbox chunker.
- Fan-out concurrency is capped at 10 sandboxes per stage per review (`MAX_CONCURRENT_SANDBOXES`);
  the global ceiling is the tasks queue worker.

## Per-review breakdown

Sorted by incident. `Review turns` marked `*` are estimated (all perspectives on all chunks,
the pattern every observed multi-chunk review followed); all other numbers are read from run data.

| Incident | PR                        | Chunks | Perspectives | Review turns            | Validation turns | Total sandboxes        |
| -------- | ------------------------- | ------ | ------------ | ----------------------- | ---------------- | ---------------------- |
| INC-990  | posthog#93633             | 1      | 3            | 4                       | 6                | 10                     |
| INC-987  | posthog#93635             | 2      | 3            | 8\*                     | 23               | 31\*                   |
| INC-975  | posthog-js#4750           | 1      | 2            | 3                       | 4                | 7                      |
| INC-938  | posthog#93636             | 1      | 3            | 4                       | 15               | 19                     |
| INC-931  | posthog#93637             | 4      | 3            | 13                      | 23               | 36                     |
| INC-921  | posthog#93680             | 71     | 3            | 162 of 239 (terminated) | 0                | 163 (incl. 1 chunking) |
| INC-834  | posthog#93638             | 1      | 3            | 4                       | 6                | 10                     |
| INC-828  | posthog#93639             | 1      | 3            | 4                       | 5                | 9                      |
| INC-815  | posthog#93641             | 1      | 3            | 4                       | 8                | 12                     |
| INC-814  | charts#15072              | 1      | 1            | 2                       | 3                | 5                      |
| INC-775  | charts#15073              | 1      | 1            | 2                       | 0                | 2                      |
| INC-717  | posthog#93643             | 1      | 3            | 4                       | 6                | 10                     |
| INC-711  | posthog-cloud-infra#10210 | 1      | 3            | 4                       | 2                | 6                      |
| INC-702  | posthog#93644             | 2      | 3            | 8                       | 20               | 28                     |
| INC-694  | posthog#93645             | 1      | 1            | 2                       | 1                | 3                      |
| INC-622  | posthog#93648             | 1      | 3            | 4                       | 6                | 10                     |
| INC-611  | posthog#93649             | 1      | 3            | 4                       | 5                | 9                      |
| INC-564  | posthog#93650             | 1      | 2            | 3                       | 3                | 6                      |
| INC-563  | posthog-cloud-infra#10211 | 1      | 3            | 4                       | 3                | 7                      |
| INC-542  | posthog#93651             | 1      | 3            | 4                       | 17               | 21                     |
| INC-536  | posthog#93653             | 1      | 3            | 4                       | 0                | 4                      |
| INC-496  | posthog#93656             | 1      | 3            | 4                       | 13               | 17                     |
| INC-488  | posthog#93657             | 1      | 3            | 4                       | 6                | 10                     |
| INC-487  | posthog#93658             | 1      | 3            | 4                       | 5                | 9                      |
| INC-392  | posthog#93659             | 1      | 3            | 4                       | 14               | 18                     |
| INC-390  | posthog#93660             | 1      | 3            | 4                       | 12               | 16                     |
| INC-384  | posthog#93663             | 1      | 3            | 4                       | 1                | 5                      |
| INC-271  | charts#15074              | 1      | 2            | 3                       | 0                | 3                      |
| INC-242  | posthog#93668             | 1      | 3            | 4                       | 8                | 12                     |
| INC-239  | charts#15075              | 1      | 2            | 3                       | 7                | 10                     |
| INC-218  | posthog#93670             | 1      | 3            | 4                       | 8                | 12                     |
| INC-193  | posthog#93671             | 1      | 3            | 4                       | 8                | 12                     |
| INC-154  | posthog#93673             | 1      | 3            | 4                       | 9                | 13                     |
| INC-120  | posthog#93676             | 1      | 2            | 3                       | 6                | 9                      |

## Observations

- **Validation dominates on finding-heavy PRs.** Across completed reviews, validation turns (245)
  outnumber review turns (138) — the per-candidate validation fan-out is the main cost driver
  once a PR yields more than a handful of findings.
- **Typical cost is small.** 29 of 33 completed reviews stayed within 3–21 sandboxes; only
  multi-chunk PRs went higher.
- **One oversized PR dwarfed everything.** INC-921 (446 files, ~70k additions) consumed ~163
  sandboxes before manual termination — about 30% of the whole experiment — and would have
  reached roughly 300+ with its validation stage. It also surfaced two product gaps: no way to
  cancel a running review from the UI/API (required a manual Temporal workflow termination), and
  no trigger-time size cap that would have rejected or warned on a PR this large.
- **Zero-finding reviews are near-free.** The four reviews that published nothing cost 2–4
  sandboxes each: skipping validation eliminates most of the cost.

## Caveats

- Counts are reconstructed from the pipeline's progress counters and final per-review stats,
  not from a sandbox-level ledger; treat totals as accurate to within a few turns.
- One review's turn count is estimated (marked `*`).
- Sandbox counts are not token costs: turns differ in length, and validation turns are
  typically shorter than perspective review turns.
