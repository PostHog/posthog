# Signals grouping iteration harness

## What this is

An offline test harness for iterating on signal grouping strategies without touching production databases or waiting for the full Temporal pipeline.

The Signals product groups incoming signals (bug reports, feature requests, alerts) into **SignalReports** via embedding similarity + LLM matching.
The current production strategy is `pr_specificity_and_group_aware` — see [Strategies and results](#strategies-and-results) for how we got there.

This harness lets you:

- Run grouping strategies on a fixed set of 42 real signals, in memory, in ~5-7 minutes
- Compare strategies via an LLM judge that scores group coherence and detects weak-chaining
- Iterate fast: embeddings are cached, no DB connections needed

## Test dataset

`data/test_signals.json` is a committed fixture of 42 real signals.
Everyone tests against the same data, so results are comparable across machines and runs.

The signals are curated to include both well-grouped and poorly-grouped cases:

| Source report              | Count | Expected behavior                                 |
| -------------------------- | ----- | ------------------------------------------------- |
| Date filtering features    | 9     | Should stay as one group — coherent feature area  |
| Mixed bag (weak-chained)   | 18    | Should be **split** — this is the key test case   |
| K8s probes / feature flags | 8     | Should stay as one group — coherent infra concern |
| LLM analytics traces       | 2     | Should stay together                              |
| Various singletons         | 5     | Each creates its own group                        |

## How it works

1. Signals are processed sequentially (same as production) through a pluggable `GroupingStrategy`
2. Embeddings are generated via OpenAI API and cached to `cache/` (gitignored)
3. LLM calls (query generation, matching) use the Anthropic API directly
4. An LLM evaluator judges the resulting groups for coherence and weak-chaining

## Architecture reference

See [ARCHITECTURE.md](../ARCHITECTURE.md) for full details on the production pipeline.
Key files for the production grouping logic:

- `products/signals/backend/temporal/grouping.py` — prompts, LLM calls, workflow
- `products/signals/backend/temporal/llm.py` — `call_llm()` helper, model config
- `products/signals/backend/temporal/types.py` — shared data types

**Note:** This harness copies the production prompts rather than importing them,
because `grouping.py` has top-level Django/Temporal imports that can't be loaded standalone.
Each copied prompt has a comment pointing to its source file — keep them in sync when changing prompts.

## Setup

### Prerequisites

- Python 3.11+
- API keys in `.env` at the repo root:

  ```shell
  OPENAI_API_KEY=sk-...        # for embeddings (text-embedding-3-small)
  ANTHROPIC_API_KEY=sk-ant-... # for LLM calls (claude-sonnet-4-5)
  ```

## Development

After any code change, lint before committing:

```bash
ruff check products/signals/grouping-iterations/ --fix && ruff format products/signals/grouping-iterations/
```

## Running

```bash
# Full run with evaluation (~5-7 min for 42 signals)
python products/signals/grouping-iterations/run.py

# Tag a run with a note for context
python products/signals/grouping-iterations/run.py --note "baseline before prompt changes"

# Quick smoke test (first N signals, skip evaluation)
python products/signals/grouping-iterations/run.py --limit 5 --skip-eval

# Use a specific strategy
python products/signals/grouping-iterations/run.py --strategy my_new_strategy
```

### Output

The harness prints to stdout and saves a full run log to `runs/` (gitignored):

1. **Summary metrics** (printed first for quick comparison)
2. Per-signal processing log (queries generated, match decisions)
3. Final groups with signal contents and original report IDs
4. Evaluation report: per-group coherence scores, under-grouping detection, overall quality 1-5

### Comparing runs

Each run produces deterministic **summary metrics** designed for quick numerical comparison:

| Metric                | What it measures                                                |
| --------------------- | --------------------------------------------------------------- |
| Overall score         | LLM holistic judgment (1-5)                                     |
| Weighted coherence    | Average coherence weighted by group size (higher = better)      |
| Weak-chain groups     | Groups with coherence ≤ 2 and 3+ signals (lower = better)       |
| Misplaced signals     | Total signals that don't belong in their group (lower = better) |
| Under-grouping misses | Singletons that should have been merged (lower = better)        |

### Run history

Each run is saved to `runs/<timestamp>_<strategy>.md` with:

- **Context**: strategy name, signal count, note
- **Metrics**: comparison table (overall score, weighted coherence, weak-chain groups, misplaced signals, under-grouping)
- **Processing log**: per-signal decisions
- **Groups**: full grouping output
- **Evaluation**: judge assessment + raw JSON

Use `--note` to tag runs (e.g. `--note "added distance threshold"`).
Compare runs by looking at the Metrics table in each file — they're sorted chronologically by filename.

### Tips

- Running full runs (without `--limit`) is preferable for meaningful comparison
- You can start multiple runs in parallel (for example, 3) — evaluation is non-deterministic, so multiple runs give better signal
- Use `--limit 3 --skip-eval` for quick smoke tests when iterating on code

## Strategies and results

The current production strategy is **`pr_specificity_and_group_aware`** — the only strategy with code in this directory.
All other strategies below are historical records documenting what was tested and why it didn't work as well.
Do not re-implement these approaches without reviewing the notes.

| Strategy                                                              | Overall | Weighted coherence | Groups (multi/single) | Weak-chain | Misplaced | Under-grouping |
| --------------------------------------------------------------------- | ------- | ------------------ | --------------------- | ---------- | --------- | -------------- |
| `one_to_one_linking` (original baseline)                              | 2/5     | 1.97–2.65          | 15–18 (5–6 / 9–12)    | 2–3        | 13–18     | 1–4            |
| `group_aware` (full report context)                                   | 2–3/5   | 2.86–3.71          | 31–33 (4–6 / 25–28)   | 1–2        | 4–6       | 1–12           |
| `verification_gate` (LLM verification)                                | 2/5     | 2.87–3.36          | 29–30 (10–11 / 18–20) | 3–5        | 6–10      | 1–2            |
| `multilink` (transitive verification)                                 | 2/5     | 2.53–2.87          | 16–18 (6–7 / 10–11)   | 3          | 13–18     | 0–1            |
| `pr_specificity` v1 (PR-title gate, cold-start skip)                  | 2/5     | 2.64–2.92          | 27–29 (9–11 / 16–20)  | 5–6        | 8–11      | 1              |
| `pr_specificity` v2 (no cold-start, tighter prompt)                   | 2–3/5   | 3.23–4.21          | 33–34 (5–6 / 27–29)   | 1–2        | 2–5       | 1–4            |
| **`pr_specificity_and_group_aware`** (group context + title feedback) | 2–3/5   | 3.78–4.50          | 35–37 (4–6 / 29–33)   | 0–1        | 1–2       | 1–3            |
| `pr_specificity_and_group_aware_v2` (softened specificity prompt)     | 2–3/5   | 3.39–3.82          | 31–32 (7 / 24–25)     | 2          | 3–6       | 1–2            |
| `pr_specificity_and_group_aware_v3` (surgical prompt adjustment)      | 2–3/5   | 3.13–4.08          | 33–35 (5–6 / 27–30)   | 1–2        | 3–5       | 1–2            |

### Strategy notes (code removed — kept for historical reference)

- **one_to_one_linking** (original baseline): Signal-to-signal matching with no group context. Good at discovery, no filtering. Chains unrelated signals through shared keywords — the weak-chaining problem that motivated this iteration.
- **group_aware**: Shows LLM full report context. Too conservative — over-splits into singletons.
- **verification_gate**: Adds LLM "does this fit?" check. Subjective, doesn't reliably catch bridges.
- **multilink**: One-to-one linking + embedding-based transitive verification. Fails because embeddings can't distinguish "same domain" from "same work item" — signals sharing product vocabulary pass the check.
- **pr_specificity v1**: One-to-one linking + one LLM call asking "write a PR title for all signals; is it specific enough for one engineer?" Forces synthesis over judgment. Cold-start skip (only checks groups with 2+ signals) leaves initial weak pairings unchecked.
- **pr_specificity v2**: Same as v1 but runs the PR-specificity check on ALL matches (no cold-start skip) + tighter prompt with more red flags. Best results so far: 70–85% reduction in misplaced signals vs baseline. Trade-off: more singletons, but multi-signal groups are high quality.
- **pr_specificity_and_group_aware** (production): Builds on pr_specificity v2 with three enhancements: (1) group-title context in matching prompt so LLM sees what group it's joining, (2) multi-query agreement summary so LLM knows which groups were found by multiple independent queries, (3) title feedback loop where confirmed PR titles become the group's updated title for future matching.
- **pr_specificity_and_group_aware_v2**: Softened specificity prompt — replaced "err on side of rejecting" + "different engineers" heuristic with explicit ACCEPT/REJECT criteria. Overcorrected: more multi-signal groups but re-introduced weak chaining (misplaced 3–6 vs 1–2 in v1).
- **pr_specificity_and_group_aware_v3**: Surgical adjustment — kept v1's default-reject but removed "different engineers" heuristic and added narrow "same underlying issue" exception (duplicate bug reports, root cause + mitigation). Still worse than v1: the matching step proposes bad matches (keyword overlap) that any loosening of the specificity gate re-exposes. **Conclusion: the bottleneck is the matching step, not the specificity prompt.**

## Adding a new strategy

1. Create `my_strategy.py` implementing the `GroupingStrategy` protocol:

```python
from harness import EmbeddingCache, GroupingDecision, InMemorySignalStore, TestSignal

class MyStrategy:
    async def assign_signal(
        self,
        signal: TestSignal,
        signal_embedding: list[float],
        store: InMemorySignalStore,
        embedding_cache: EmbeddingCache,
    ) -> GroupingDecision:
        # Your grouping logic here
        ...
```

2. Register it in `run.py`'s `get_strategy()`:

```python
def get_strategy(name: str):
    if name == "pr_specificity_and_group_aware":
        from pr_specificity_and_group_aware import PRSpecificityAndGroupAwareStrategy
        return PRSpecificityAndGroupAwareStrategy()
    elif name == "my_strategy":
        from my_strategy import MyStrategy
        return MyStrategy()
```

3. Run and compare:

```bash
python products/signals/grouping-iterations/run.py --strategy my_strategy
```

## Regenerating the test dataset

If you need to refresh the fixture from a new ClickHouse export:

```bash
# 1. Export signals from ClickHouse
posthog-cli exp query run "select product, document_type, document_id, timestamp, inserted_at, content, metadata from document_embeddings where model_name = 'text-embedding-3-small-1536' and product = 'signals' limit 1000" > /tmp/signals_export.json

# 2. Regenerate the fixture
python products/signals/grouping-iterations/data/prepare_test_set.py --input /tmp/signals_export.json

# 3. Commit the updated fixture
```
