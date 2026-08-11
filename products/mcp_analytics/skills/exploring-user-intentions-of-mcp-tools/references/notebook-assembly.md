# Assembling the notebook

The notebook is the deliverable, so it has to stand on its own: someone opening it a month later should be able to see the corpus, re-run the clustering, and change the cluster count without asking how it was made.

Clustering runs in the notebook's Python cell rather than anywhere else because it needs no credentials — TF-IDF and scikit-learn are already in the sandbox image.
Only the facet extraction needs a model, and that already happened in your context before the notebook existed.

## Cell order

Add cells in dependency order; a cell that reads another's dataframe needs that cell to have completed a run.

### 1. Create the notebook

**Get the counts right before writing a word of the intro.** A notebook's opening paragraph is where corpus sizes are stated, and it is the one cell you cannot edit afterwards — markdown cells carry no addressable `node_id`, so a wrong number means destroying and rebuilding. Reconcile the corpus query and the caller-share query against each other first, and quote only figures that come from the window you actually analyzed.

```json
notebooks-create-markdown
{
  "title": "Why people use <tool>",
  "markdown": "Starting-point taxonomy for `<tool>`, 90 days to <date>.\n\nEach session's goal is reconstructed from its opening tool calls, then clustered on goal text. Clusters below 5 sessions are suppressed. No customer names or raw intents appear below."
}
```

Returns the `notebook_id` — this is the short id from the URL, and it is what every later call needs.

### 2. Raise compute before the first Python cell

```json
notebooks-configure-compute
{ "short_id": "<id>", "cpu_cores": 4, "memory_gb": 8 }
```

The default 1 core / 2 GB is enough to start a kernel and not much else; agglomerative clustering on a few hundred short strings will sit there.
Do this **first**. If a kernel is already running, the response sets `restart_required`, and restarting discards every materialized dataframe.

### 3. The corpus cell (sql)

Add the corpus query from the skill's step 2 with `dataframe_name: "corpus"` and a title like "Sessions that reached the tool".
This is what makes the notebook auditable — a reader can see exactly which sessions the taxonomy covers, and re-run it for a fresh window.

### 4. The clustering cell (python)

Inline the facets you extracted, grouped by distinct `(goal, data_touched, role)` combination with a count.
Extraction normalizes onto a small shared vocabulary, so a 500-session corpus collapses to roughly 120 combinations and about 8 KB of cell source, rather than 30 KB of one row per session.

**The starting intentions are the primary table, not the clusters.** See "What the clustering is really doing" below for why.

```python
# One row per distinct facet combination, with how many sessions produced it.
FACET_COUNTS = [
    ("build a recurring metrics digest", True, "publish_findings", 94),
    ("investigate an error spike", True, "publish_findings", 11),
    # … one per distinct combination
]

from collections import Counter

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

N_CLUSTERS = 28
MIN_SESSIONS = 5

FACETS = [(g, d, r) for g, d, r, n in FACET_COUNTS for _ in range(n)]

by_goal = {}
for g, d, r in FACETS:
    by_goal.setdefault(g, []).append((d, r))

intentions = pd.DataFrame([
    {
        "starting_intention": g,
        "sessions": len(rows),
        "share_pct": round(100 * len(rows) / len(FACETS), 1),
        "data_pct": round(100 * sum(d for d, _ in rows) / len(rows)),
        "top_role": Counter(r for _, r in rows).most_common(1)[0][0],
    }
    for g, rows in by_goal.items()
    if len(rows) >= MIN_SESSIONS
]).sort_values("sessions", ascending=False).reset_index(drop=True)

goals = [g.lower().strip() for g, _, _ in FACETS]
# min_df=1: goals are short, so dropping singleton terms leaves some rows
# all-zero, and cosine linkage rejects zero vectors outright.
vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1, sublinear_tf=True)
X = vec.fit_transform(goals)
assignments = AgglomerativeClustering(
    n_clusters=N_CLUSTERS, metric="cosine", linkage="average"
).fit_predict(normalize(X.toarray()))

print(f"{len(FACETS)} sessions, {len(by_goal)} distinct starting intentions")
print(f"{len(intentions)} intentions at or above {MIN_SESSIONS} sessions "
      f"({intentions['sessions'].sum()} of {len(FACETS)} sessions)\n")
print("Rollup: which intentions the clustering merges together")
print("=" * 66)

roll = []
for cid in range(N_CLUSTERS):
    members = [FACETS[i] for i in np.flatnonzero(assignments == cid)]
    if len(members) < MIN_SESSIONS:
        continue
    counts = Counter(g for g, _, _ in members).most_common()
    roll.append((len(members), counts, round(100 * sum(d for _, d, _ in members) / len(members))))

for n, counts, data_pct in sorted(roll, key=lambda r: -r[0]):
    print(f"\n{n:>4}  {100 * n / len(FACETS):>4.1f}%  data={data_pct:>3}%  {counts[0][0]}")
    for g, k in counts[1:]:
        print(f"{'':>22}+ {g} ({k})")

print(f"\n{len(FACETS) - sum(r[0] for r in roll)} sessions fall below the "
      f"{MIN_SESSIONS}-session floor and are suppressed.")

intentions
```

Note there is no `top_terms` column. Lift-ranked TF-IDF terms look informative and are not: the goal strings are already canonical after extraction, so the terms just restate the label back to you in a worse form.

### Why the grouping is by hand

The skill embeds intentions once, in `scripts/audit_intentions.py`, to catch drift. It deliberately does not embed them to build the themes. Three reasons, in order of weight:

**The input is already canonical.** Extraction collapses hundreds of sessions onto a small controlled vocabulary, so the semantic variance embeddings recover has largely been removed before they see it. Measured on the `workflows-create` corpus, the highest similarity between any two of 105 intentions was 0.819 — they are already well separated.

**Grouping is purposive, and embeddings cannot see the purpose.** `verify a feature flag configuration` belongs with analytics work because it is checking product state, not with `manage feature flag rollout`, which changes it. An embedding puts the two flag phrases together every time. Semantically right, analytically wrong.

**It reinstates the caveat.** An embedding grouping beats TF-IDF comfortably, but it is still unaudited, and once caller share is computed per theme any bad merge propagates into every derived number.

Two conditions flip this. At several thousand intentions hand-grouping stops being feasible. And if the taxonomy becomes a standing report compared across windows, a deterministic grouping beats a better but unrepeatable one — otherwise drift between runs is indistinguishable from drift in user behavior.

**If anything hangs off the grouping, assign themes by hand instead of clustering.** TF-IDF merges on shared words rather than shared meaning, and on short canonical strings it visibly misfires — it put `investigate a production error` inside `analyze revenue attribution` because both contain "investigate", and `migrate feature flags` inside `measure feature usage volume` on "feature". You can document those errors while the clusters are decorative. You cannot once a caller breakdown or any other cut is computed per cluster, because the error propagates into every derived number.

Extraction already applied semantic judgment to produce the intentions. Applying the same judgment to group 70-odd short phrases into a dozen themes is cheap, and it removes a whole class of caveat:

```python
THEMES = {
    "recurring reporting": ["build a recurring metrics digest", "report on a launch", ...],
    "automated monitoring": ["run a scheduled anomaly scout", ...],
}
theme_of = {intent: theme for theme, intents in THEMES.items() for intent in intents}

unmapped = sorted({i for i, *_ in ROWS} - set(theme_of))
assert not unmapped, f"intentions with no theme: {unmapped}"
assert len(theme_of) == sum(len(v) for v in THEMES.values()), "an intention appears in two themes"
```

Say in the notebook that the grouping is by hand. A reader who disagrees with a theme can fall back to the intentions table, which is the raw unit either way.

`MIN_SESSIONS` applies to the intentions table too. An intention with one session is a cluster of one, which is exactly what the aggregation threshold exists to prevent, even when the string itself carries no proper nouns.

**Assert the corpus size in the cell.** You are transcribing a hundred-odd counted rows into a tool call, and a dropped or mistyped row changes every share in the table without erroring:

```python
assert len(FACETS) == 428, f"expected 428 sessions, got {len(FACETS)}"
```

This caught a real slip — one omitted row and four mistyped counts, showing up as 418 sessions instead of 428. Every percentage was wrong and nothing complained.

### 4b. Inline once, summarize in SQL

Publish **one** long-format frame from the Python cell — `(starting_intention, theme, caller, data_touched, sessions)` — and build every summary table as a SQL cell over it. A SQL cell that names a local dataframe runs on the notebook's own engine, so the intentions table, the caller-per-intention table and the caller-per-theme table are each a short `GROUP BY` with no repeated literal.

That matters because the literal is the risky part: you are hand-transcribing a hundred-odd counted rows into a tool call, and every duplicate is another chance to mistype one. Keep portable SQL in those cells (`sum(case when ... then ... else 0 end)`, `min(col)` rather than `any(col)`) so the same query works whichever engine runs it.

### 4c. The caller tables

Two are worth publishing, and they answer different questions:

- **Caller share for the tool** — one row per caller, as a percentage of all sessions and of organic sessions. This one is a ClickHouse cell over `$mcp_tool_call`, not over the facets frame, because it should include the automated traffic you filtered out.
- **Caller share per intention, and per theme** — where each population actually spends its time.

Callers concentrate far harder than the totals suggest, and that is the point. In the `notebooks-create` run, automated monitoring was 94% PostHog Desktop, product analysis and feedback review both above 60% Claude Code, web performance 43% plugin. Customer and account analysis was 68% Cowork and Claude.ai combined against 6% Claude Code — a sales workflow on entirely different surfaces from the engineering ones.

The conclusion to look for is whether one population exists or several. If themes split cleanly by caller, there is no single user to design for, and that is worth saying plainly.

**Treat `unattributed` as a gap, not a caller.** A theme that looks concentrated there is missing instrumentation, not a population. Say so next to the number, because it will otherwise read as a finding.

### 5. Example traces (optional)

If the taxonomy needs evidence behind it, resolve one or two sessions per intention to an AI observability trace, using the join in the skill's "Linking an intention to real sessions".

**Carry the session count and share on every row**, the same two columns the intentions table has. Without them the table reads as if every intention were equally common, and — more importantly — it hides whether a row cleared the aggregation floor.

**Only list intentions at or above `MIN_SESSIONS`.** Linking named sessions under a rare intention is precisely what the threshold exists to prevent: the smaller the group, the more a link identifies someone. This is easy to get wrong, because the intentions with the most interesting traces are often the rarest. A first pass at this table carried three intentions at 2, 3, and 4 sessions, and only adding the count columns made that visible.

Keep the `$mcp_session_id` and trace URL, and leave the raw `$mcp_intent` out. The ids are opaque; the intents carry customer, project, and product names verbatim.

Say in the table what the link actually opens: PostHog's server-side query work during that session, not the user's conversation.

### 6. The findings cell (markdown)

Write the shares out in prose, led by the largest starting intentions.
Include the skew correction — if a keyword filter turned out to leak, state the corrected share here rather than quietly using the filtered number.
If the rollup merged unrelated intentions, say so rather than quoting the merged cluster as one number.

## What the clustering is really doing

The pipeline summarizes, then clusters, and **the summarizing step does nearly all the work.**

Extraction maps every session onto a small shared vocabulary by design — a 499-session run produced only 73 distinct goal strings. By the time TF-IDF sees them, the grouping has already happened. The clustering is a second, looser pass that merges related labels; it is not discovering structure.

That has two consequences worth designing around.

**Report the intentions, roll up the clusters.** The 73 strings are the taxonomy. The 15 clusters are a convenience view over them.

**TF-IDF merges on shared words, not meaning, and on short canonical strings it visibly misfires.** Real merges from the `notebooks-create` run:

| Merged into                      | Wrongly absorbed                                           | Shared token  |
| -------------------------------- | ---------------------------------------------------------- | ------------- |
| investigate attribution tracking | investigate a production error (4)                         | "investigate" |
| measure feature usage volume     | migrate feature flags (1), manage feature flag rollout (1) | "feature"     |
| run a product health review      | evaluate a product for adoption (3)                        | "product"     |

Read the rollup and discount clusters built on a shared verb or noun rather than a shared goal.
Raising `N_CLUSTERS` splits some of these apart; it will not fix all of them, because the failure is lexical rather than a resolution problem.

`N_CLUSTERS` around `len(FACETS) / 18` is a reasonable start.

## Gotchas

**`dataframe_name` publishes the cell's last expression, not the variable it is named after.**
Ending the cell with `clusters.sort_values("sessions").head(20)` publishes those 20 rows, and a downstream cell reading the frame sees only those.
End the cell with the bare dataframe. An empty frame downstream fails as `InvalidInputException: Need a DataFrame with at least one column`, which does not point back here at all.

**The parameter name changes between tools.** `notebooks-add-cell` takes `notebook_id`; `notebooks-run-cell-result` and `notebooks-configure-compute` take `short_id`. Same value, different key.

**The first Python cell is slow** because the sandbox kernel is booting. `notebooks-add-cell` waits about 45 seconds and may return `status: running`; poll `notebooks-run-cell-result` with both `run_id` and `short_id`, a few seconds apart.

**That poll can lag the truth by minutes.** On a run that finished in 5 seconds, `notebooks-run-cell-result` kept reporting `running` for about three more.
`notebooks-list-frames` showed the finished dataframe, with its real column list and row count, straight away.
When a poll looks stuck, check the frames before reaching for `notebooks-run-cell-interrupt` — interrupting a cell that already succeeded costs you the kernel state for no reason.

**If a cell hangs**, `notebooks-run-cell-interrupt` clears it. A kernel that has gone to `stopped` with a run still showing `running` needs the interrupt before anything else will execute.

**Iterate with `notebooks-update-cell`** rather than adding a new cell each time you change the cluster count — otherwise the notebook accumulates dead attempts that a reader has to scroll past.
