# Assembling the notebook

The notebook is the deliverable, so it has to stand on its own: someone opening it a month later should be able to see the corpus, see which sessions each intention covers, and disagree with a theme without asking how it was made.

The notebook itself needs no credentials. Every cell is either SQL or a small pandas reshape, and the one step that needs a model — the facet extraction — already happened in your context before the notebook existed.

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

**Do not paste the skill's step 2 query into this cell.** That query concatenates the raw `$mcp_intent` text so you can read it, and a notebook is shareable: anyone with the link reads whatever the cell returns, including the customer names, project ids and pasted credentials those strings carry. Step 2 is for reading in your own context and stops there.

The published cell is a narrower query over the same sessions, with the intent text replaced by the tool name alone:

```sql
-- inside the steps CTE, instead of concat(tool, ': ', substring(intent, 1, 130))
coalesce(nullIf(toString(properties.$mcp_tool_name), ''), toString(properties.tool_name)) AS step
```

Everything else is identical. Publish it with `dataframe_name: "corpus"` and a title like "Sessions that reached the tool". The result is `sid`, `caller`, `org` and an `opening_tools` sequence such as `execute-sql > read-data-schema > workflows-list`, which is enough to audit which sessions the taxonomy covers and carries no customer text.

### 4. The facets cell (python)

Inline one row per session, keyed on `sid`, and let the corpus frame supply the caller and the org.

Pre-aggregating by distinct facet combination is smaller: a 500-session corpus collapses to roughly 120 rows and about 8 KB of source, against 30 KB for one row per session. It is still the wrong trade. As soon as the analysis needs the org, the combination key inflates back to roughly the session count, because most orgs hold a single session. Keyed on `sid`, the literal joins to anything, and transcribing it involves no counting.

**The starting intentions are the primary table.** Themes are a hand-assigned column, not a computed one. See "Why the grouping is by hand" below.

```python
# One row per session: sid|starting intention|theme|data_touched|destination.
#
# The starting intention is the goal the person held before any tool was chosen.
# It is not a recorded property. $mcp_intent records the action an agent took,
# so each label here was written by reading that session's opening calls.
# Proper nouns were stripped at that point, not later.
DATA = '''
a1b2c3d4|build a recurring metrics digest|recurring reporting|1|slack
e5f6a7b8|fix a misfiring workflow|maintenance|0|unclear
'''

import pandas as pd

MIN_SESSIONS = 5
COLUMNS = ["sid", "starting_intention", "theme", "data_touched", "destination"]

facets = pd.DataFrame([line.split("|") for line in DATA.strip().split("\n")], columns=COLUMNS)
facets["data_touched"] = facets["data_touched"].astype(int)

assert len(facets) == 428, f"expected 428 sessions, got {len(facets)}"
assert facets["sid"].is_unique, "a sid appears twice"

kept = facets.groupby("starting_intention").filter(lambda g: len(g) >= MIN_SESSIONS)
print(f"{len(facets)} sessions, {facets['starting_intention'].nunique()} distinct intentions")
print(f"{kept['starting_intention'].nunique()} at or above {MIN_SESSIONS} sessions "
      f"({len(kept)} of {len(facets)} sessions kept)")

facets
```

There is no TF-IDF step. An earlier version clustered the goal strings to build the themes, and that is now a hand-assigned column instead, because the per-org table reads the theme and a lexical misfire would propagate into every number derived from it. The measured misfires are kept below, as the reason rather than as a caveat.

### Why the grouping is by hand

The skill embeds intentions once, in `scripts/audit_intentions.py`, to catch drift. It deliberately does not embed them to build the themes. Three reasons, in order of weight:

**The input is already canonical.** Extraction collapses hundreds of sessions onto a small controlled vocabulary, so the semantic variance embeddings recover has largely been removed before they see it. Measured on the `workflows-create` corpus, the highest similarity between any two of 105 intentions was 0.819 — they are already well separated.

**Grouping is purposive, and embeddings cannot see the purpose.** `verify a feature flag configuration` belongs with analytics work because it is checking product state, not with `manage feature flag rollout`, which changes it. An embedding puts the two flag phrases together every time. Semantically right, analytically wrong.

**It reinstates the caveat.** An embedding grouping beats a lexical one comfortably, but it is still unaudited, and once the per-org table is computed per theme any bad merge propagates into every derived number.

Two conditions flip this. At several thousand intentions hand-grouping stops being feasible. And if the taxonomy becomes a standing report compared across windows, a deterministic grouping beats a better but unrepeatable one — otherwise drift between runs is indistinguishable from drift in user behavior.

**If anything hangs off the grouping, assign themes by hand instead of clustering.** TF-IDF merges on shared words rather than shared meaning, and on short canonical strings it visibly misfires — it put `investigate a production error` inside `analyze revenue attribution` because both contain "investigate", and `migrate feature flags` inside `measure feature usage volume` on "feature". You can document those errors while the clusters are decorative. You cannot once a caller breakdown or any other cut is computed per cluster, because the error propagates into every derived number.

Extraction already applied semantic judgment to produce the intentions. Applying the same judgment to group 70-odd short phrases into a dozen themes is cheap, and it removes a whole class of caveat:

```python
THEMES = {
    "recurring reporting": ["build a recurring metrics digest", "report on a launch", ...],
    "automated monitoring": ["run a scheduled anomaly scout", ...],
}
theme_of = {intent: theme for theme, intents in THEMES.items() for intent in intents}

unmapped = sorted(set(facets["starting_intention"]) - set(theme_of))
assert not unmapped, f"intentions with no theme: {unmapped}"
assert len(theme_of) == sum(len(v) for v in THEMES.values()), "an intention appears in two themes"
```

Say in the notebook that the grouping is by hand. A reader who disagrees with a theme can fall back to the intentions table, which is the raw unit either way.

`MIN_SESSIONS` applies to the intentions table too. An intention with one session is a cluster of one, which is exactly what the aggregation threshold exists to prevent, even when the string itself carries no proper nouns.

**Assert the corpus size in the cell.** You are transcribing a hundred-odd counted rows into a tool call, and a dropped or mistyped row changes every share in the table without erroring:

```python
assert len(facets) == 428, f"expected 428 sessions, got {len(facets)}"
```

This caught a real slip — one omitted row and four mistyped counts, showing up as 418 sessions instead of 428. Every percentage was wrong and nothing complained.

### 4b. Publish the population as a second literal, not a joined query

The Python cell publishes `facets`, keyed on `sid`. The caller and the org arrive as a **second Python literal** keyed on the same `sid`, and every population table is a SQL cell joining the two:

```sql
SELECT p.org, f.theme, f.starting_intention, count(*) AS sessions
FROM facets AS f
JOIN population AS p ON f.sid = p.sid
GROUP BY p.org, f.theme, f.starting_intention
ORDER BY sessions DESC
```

**Both literals are executable source, so nothing untrusted goes into them raw.** The caller and org come from client-controlled properties, and a value containing `'''` would close the literal and execute what follows when the cell runs. The skill's corpus query constrains them to a safe charset and emits `unsafe-caller-value` for anything else; transcribe what that query returns and never widen it by hand. The goal labels are safe by a different route — you wrote them.

**Joining the corpus cell instead does not work, and the reason is worth knowing before you design around it.** A SQL cell that another cell joins has to materialize into the notebook kernel, and materialization runs under its own caps ([`frame_materialize.py`](../../../../products/notebooks/backend/temporal/frame_materialize.py)): a 50 GB scan budget, a 2 GB result cap, 500k rows, 16 threads. A corpus query grouping 90 days of `$mcp_tool_call` by session id blows them and the cell fails with:

```text
This query exceeds the frame materialization limits (scan or memory budget). Narrow it and re-run.
```

Three things about that message matter:

- **It does not say which budget you blew.** The same string is mapped from ClickHouse codes 158 `TOO_MANY_ROWS`, 241 `MEMORY_LIMIT_EXCEEDED` and 307 `TOO_MANY_BYTES`. The time limit and the 2 GB result cap have their own distinct messages, so receiving this one rules both of those out and nothing else.
- **Narrowing the query may not help.** 50 GB is generous, and a high-cardinality `GROUP BY` over every session in the project with a `person.properties` join is a memory shape rather than a scan shape. Rewriting the corpus query as a single pass with no session subquery failed identically, which is what a memory-bound failure looks like.
- **Do not narrow the window to buy headroom.** It changes which sessions the corpus holds, and the labelled frame is a fixed snapshot, so the two stop describing the same population. That trade is never worth it.

The corpus cell still earns its place as the auditable copy of the same two columns. It just cannot be the join source.

Keep portable SQL in the joining cells (`sum(case when ... then ... else 0 end)`, and `min(col)` rather than `any(col)`) so the same query works whichever engine runs it.

### 4c. Pin the ClickHouse cells to absolute timestamps

Both ClickHouse cells — the corpus and the caller share — should use an explicit `timestamp >= toDateTime(...) AND timestamp < toDateTime(...)` range rather than `now() - INTERVAL 90 DAY`.

The labelled frame is a snapshot taken while you read the corpus. A rolling window keeps moving underneath it. On the `workflows-create` run the live count drifted from 761 sessions to 769 during the notebook's own construction, a few hours, while the labels stayed at 719. The header cell states the corpus size and markdown cells cannot be edited afterwards, so the drift is unfixable once it appears.

Pick the upper bound so the pinned query reproduces the counts you labelled, and verify it before writing the intro: on that run the cutoff that returned exactly 761 / 734 / 719 / 340 was two hours earlier than the sizing query's own clock.

### 4d. The population tables

Three are worth publishing, and none of them belongs inside the intentions or themes table:

- **Caller share for the tool.** One row per caller, as a share of all sessions and of organic sessions. A ClickHouse cell over `$mcp_tool_call` rather than over the facets frame, so the automated traffic you filtered out stays visible.
- **Intentions per org.** The join from 4b, carrying the theme. Read it for whether a theme is a pattern or one customer repeating.
- **Concentration.** The check from the skill's step 6, run on the caller and the org.

Callers concentrate far harder than the totals suggest, and that is the point. In the `notebooks-create` run, automated monitoring was 94% PostHog Desktop, product analysis and feedback review both above 60% Claude Code, web performance 43% plugin. Customer and account analysis was 68% Cowork and Claude.ai combined against 6% Claude Code, a sales workflow on entirely different surfaces from the engineering ones.

The conclusion to look for is whether one population exists or several. If themes split cleanly by caller, there is no single user to design for, and that is worth saying plainly.

**Treat `unattributed` as a gap, not a caller.** A theme that looks concentrated there is missing instrumentation, not a population. Say so next to the number, because it will otherwise read as a finding.

**The org is the more reliable dimension of the two.** `$mcp_organization_id` was set on every session of a 90-day `workflows-create` corpus, against roughly two thirds of sessions for the caller properties. Where the two disagree about how concentrated the traffic is, trust the org.

**The analytical tables run on org ids, not names.** They need to know that two sessions share a customer, not which customer. If the analysis exists to decide who to talk to, resolve names in a separate cell marked customer-identifying and keep these tables on 8-character prefixes — see "Default to the org id" in the skill.

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

## Why the recipe dropped its clustering step

Earlier versions ran TF-IDF and agglomerative clustering over the goal strings to build the themes. The measurements below are why that step is gone rather than tuned.

**The summarizing step already did nearly all the work.** Extraction maps every session onto a small shared vocabulary by design — a 499-session run produced only 73 distinct goal strings. By the time a clusterer saw them, the grouping had already happened. It was a second, looser pass that merged related labels, not a step discovering structure.

**TF-IDF merges on shared words, not meaning, and on short canonical strings it visibly misfires.** Real merges from the `notebooks-create` run:

| Merged into                      | Wrongly absorbed                                           | Shared token  |
| -------------------------------- | ---------------------------------------------------------- | ------------- |
| investigate attribution tracking | investigate a production error (4)                         | "investigate" |
| measure feature usage volume     | migrate feature flags (1), manage feature flag rollout (1) | "feature"     |
| run a product health review      | evaluate a product for adoption (3)                        | "product"     |

Raising the cluster count splits some of these apart and never fixes all of them, because the failure is lexical rather than a resolution problem. Hand-assigning the theme column costs a few minutes on 70-odd short phrases and removes the whole class of error.

## Gotchas

**`dataframe_name` publishes the cell's last expression, not the variable it is named after.**
Ending the cell with `clusters.sort_values("sessions").head(20)` publishes those 20 rows, and a downstream cell reading the frame sees only those.
End the cell with the bare dataframe. An empty frame downstream fails as `InvalidInputException: Need a DataFrame with at least one column`, which does not point back here at all.

**The parameter name changes between tools.** `notebooks-add-cell` takes `notebook_id`; `notebooks-run-cell-result` and `notebooks-configure-compute` take `short_id`. Same value, different key.

**The first Python cell is slow** because the sandbox kernel is booting. `notebooks-add-cell` waits about 45 seconds and may return `status: running`; poll `notebooks-run-cell-result` with both `run_id` and `short_id`, a few seconds apart.

**That poll can lag the truth by minutes.** On a run that finished in 5 seconds, `notebooks-run-cell-result` kept reporting `running` for about three more.
`notebooks-list-frames` showed the finished dataframe, with its real column list and row count, straight away.
When a poll looks stuck, check the frames before reaching for `notebooks-run-cell-interrupt` — interrupting a cell that already succeeded costs you the kernel state for no reason.

**Evaluating `any()` twice in one expression does not return the same row.** A caller column written as `multiIf(any(consumer) != '', concat('consumer:', any(consumer)), ...)` produced the prefix `consumer:` with an empty value: the condition saw a non-empty row and the branch saw an empty one. Compute the aggregates in an inner query and put the `multiIf` in the outer `SELECT`.

**`notebooks-add-cell` takes `markdown` for a markdown cell, not `code`.** Passing `code` fails with `A markdown cell requires non-empty markdown`. SQL and python cells take `code`.

**A Python frame lives in the kernel, and a SQL cell that joins it fails when it is gone.** The error is `Input registration failed: "local frame 'facets' is not in the kernel — run the node that creates it first"`, and it appears even after the Python cell reported `done` with a row count, because the frame did not survive to the join. `notebooks-list-frames` is truthful about this: it lists the frame only while it is really there. Re-run the Python cell, then run the SQL cell, and read `stale_dependents` in the update response to see what else now needs re-running.

**If a cell hangs**, `notebooks-run-cell-interrupt` clears it. A kernel that has gone to `stopped` with a run still showing `running` needs the interrupt before anything else will execute.

**Iterate with `notebooks-update-cell`** rather than adding a new cell each time you change a query — otherwise the notebook accumulates dead attempts that a reader has to scroll past.
