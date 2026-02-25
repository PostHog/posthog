# Signals grouping iteration harness

## What this is

An offline test harness for iterating on signal grouping strategies without touching production databases or waiting for the full Temporal pipeline.

The Signals product groups incoming signals (bug reports, feature requests, alerts) into **SignalReports** via embedding similarity + LLM matching.
The current strategy suffers from **weak-chaining** — signal A matches B, B matches C, but A and C are unrelated — producing bloated reports that mix unrelated issues.

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

## Running

```bash
# Full run with evaluation (~5-7 min for 42 signals)
python products/signals/grouping-iterations/run.py

# Tag a run with a note for context
python products/signals/grouping-iterations/run.py --note "baseline before prompt changes"

# Quick smoke test (first N signals, skip evaluation)
python products/signals/grouping-iterations/run.py --limit 5 --skip-eval

# Use a specific strategy
python products/signals/grouping-iterations/run.py --strategy current
```

### Output

The harness prints to stdout and saves a full run log to `runs/` (gitignored):

1. Per-signal processing log (queries generated, match decisions)
2. Final groups with signal contents and original report IDs
3. Evaluation report: per-group coherence scores, weak-chaining detection, merge/split recommendations, overall quality 1-5

### Run history

Each run is saved to `runs/<timestamp>_<strategy>.md` with:

- **Context**: strategy name, signal count, overall score, note
- **Processing log**: per-signal decisions
- **Groups**: full grouping output
- **Evaluation**: judge assessment + raw JSON

Use `--note` to tag runs (e.g. `--note "added distance threshold"`).
Compare runs by reading the files in `runs/` — they're sorted chronologically by filename.

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
    if name == "current":
        from current_strategy import CurrentStrategy
        return CurrentStrategy()
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

## File map

```text
products/signals/grouping-iterations/
├── README.md                  # This file
├── .gitignore                 # Ignores cache/, runs/, __pycache__/
├── run.py                     # Main entry point
├── harness.py                 # Core: EmbeddingCache, InMemorySignalStore, GroupingStrategy protocol
├── current_strategy.py        # Production grouping logic (in-memory)
├── evaluate.py                # LLM-based evaluation
├── data/
│   ├── prepare_test_set.py    # Regeneration script (only needed to refresh fixture)
│   └── test_signals.json      # Committed fixture — 42 curated signals
└── runs/                      # Gitignored — run logs saved here automatically
```
