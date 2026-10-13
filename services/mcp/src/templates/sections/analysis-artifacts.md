### Where an analysis lands

When work produces something worth keeping, pick the artifact before you start building it, say which one you're creating and why, and switch if the user asks for the other.

**Notebook** (`search notebooks-` for the tools) — the default for an analysis with a narrative: a question investigated step by step, where the reader needs the reasoning, the intermediate steps, and the caveats, not just the final number. Deep dives, one-off investigations, "why did X change", segmentation and cohort studies, data validation, anything whose answer is an argument rather than a metric. Notebooks interleave prose with query and analysis cells, so the method stays next to the result and the reader can re-run it.

**Dashboard** (`dashboard-create` plus `dashboard-widgets-batch-add`) — for a set of metrics someone will check repeatedly over time: monitoring, weekly or monthly tracking, team and exec overviews, launch and health boards. Reach for a dashboard when the deliverable is tiles that auto-refresh and still make sense next month, not a story with a conclusion.

**Saved insight** — a single chart answering one question, standalone or as a building block for either of the above.

Default to a notebook when the request reads as "look into", "understand", "figure out why", or "is X true" — a dashboard answers those with a wall of tiles and no conclusion. Default to a dashboard when it reads as "track", "monitor", "keep an eye on", or "report every week". If a deep dive also turns up a few metrics worth watching, write the notebook and save just those as insights; don't demote the investigation into a dashboard.
