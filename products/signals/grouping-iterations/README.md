# Signals grouping iteration harness

## What this is

An offline test harness for iterating on signal grouping strategies without touching production databases or waiting for the full Temporal pipeline.

The Signals product groups incoming signals (bug reports, feature requests, alerts) into **SignalReports** via embedding similarity + LLM matching.
The current strategy suffers from **weak-chaining** — signal A matches B, B matches C, but A and C are unrelated — producing bloated reports that mix unrelated issues.

This harness lets you:
- Run grouping strategies on real signals, in memory, in ~5-7 minutes
- Compare strategies via an LLM judge that scores group coherence and detects weak-chaining
- Iterate fast: embeddings are cached, no DB connections needed

## How it works

1. A curated test set of ~42 real signals is extracted from ClickHouse exports
2. Signals are processed sequentially (same as production) through a pluggable `GroupingStrategy`
3. Embeddings are generated via OpenAI API and cached to disk
4. LLM calls (query generation, matching) use the Anthropic API directly
5. An LLM evaluator judges the resulting groups for coherence and weak-chaining

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
  ```
  OPENAI_API_KEY=sk-...        # for embeddings (text-embedding-3-small)
  ANTHROPIC_API_KEY=sk-ant-... # for LLM calls (claude-sonnet-4-5)
  ```

### Extracting data

The test set is built from a ClickHouse export of all signals.
To replicate the export on another machine:

```bash
# Export signals from ClickHouse (run from repo root)
posthog-cli exp query run "select product, document_type, document_id, timestamp, inserted_at, content, metadata from document_embeddings where model_name = 'text-embedding-3-small-1536' and product = 'signals' limit 1000" > /tmp/signals_export.json

# Generate the test set (pass the export path)
python products/signals/grouping-iterations/data/prepare_test_set.py --input /tmp/signals_export.json
```

The prepared test set is saved to `data/test_signals.json` (gitignored).

## Running

```bash
# Full run with evaluation (~5-7 min for 42 signals)
python products/signals/grouping-iterations/run.py

# Quick smoke test (first N signals, skip evaluation)
python products/signals/grouping-iterations/run.py --limit 5 --skip-eval

# Use a specific strategy
python products/signals/grouping-iterations/run.py --strategy current
```

### Output

The harness prints:
1. Per-signal processing log (queries generated, match decisions)
2. Final groups with signal contents and original report IDs
3. Evaluation report: per-group coherence scores, weak-chaining detection, merge/split recommendations, overall quality 1-5

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

## File map

```
products/signals/grouping-iterations/
├── README.md                  # This file
├── .gitignore                 # Ignores cache/, data/test_signals.json
├── run.py                     # Main entry point
├── harness.py                 # Core: EmbeddingCache, InMemorySignalStore, GroupingStrategy protocol
├── current_strategy.py        # Production grouping logic (in-memory)
├── evaluate.py                # LLM-based evaluation
└── data/
    ├── prepare_test_set.py    # Extracts test set from full export
    └── test_signals.json      # Curated test set (gitignored, generated)
```
