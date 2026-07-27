---
description: Choose the next ClickHouse experiment from the current campaign state
---

Read `.clickhouse-autoresearch/state.json`, `.clickhouse-autoresearch/autoresearch.md`, `.clickhouse-autoresearch/out-of-scope-suggestions.md`, and the latest artifacts in `.clickhouse-autoresearch/runs/` and `.clickhouse-autoresearch/runtime/`.

Then decide the next experiment for the campaign.

Required output:

- active lane
- chosen hypothesis
- concise rationale
- expected metric movement
- semantic risk
- whether this is a normal, integration, or repair hypothesis
- what files should be edited before the next benchmark
