---
name: exploring-user-intentions-of-mcp-tools
description: >
  Build a starting-point taxonomy for an MCP tool — what users were trying to
  accomplish before they reached the tool — and publish it as a PostHog
  notebook. Reconstructs each session's goal from its opening tool calls, then
  clusters those goals into named categories with size, share, and facet mix.
  Use when the user asks "why do people use this tool?", "what are users
  actually trying to do?", "what problem brings people here?", "where do these
  sessions start?", "segment usage of <tool> by goal", or wants a Clio-style
  taxonomy of MCP usage. Complements exploring-mcp-intent-clusters, which groups
  what agents did per call rather than why the session began. The agent running
  this skill writes the goal labels itself, reading the corpus query output
  session by session — the bundled scripts cover the mechanical facets but
  measurably lose the goal's altitude, so do not delegate that field to them.
---

# Exploring user intentions of MCP tools

`$mcp_intent` records the **action** an agent was taking at the moment of a call
("create a notebook titled Q3 funnel review").
It does not record the **goal** the person started with ("investigate a conversion drop").
That goal is never written to any property — it has to be reconstructed from the shape of the session's opening calls.

This skill does that reconstruction, clusters the recovered goals, and publishes the result as a notebook.
The output answers "why do people arrive at this tool?", which no aggregation of `$mcp_tool_call` can answer on its own.

Use [`exploring-mcp-intent-clusters`](../exploring-mcp-intent-clusters/SKILL.md) instead when the question is about routing or quality — which tool serves a goal, whether agents find it, where it errors.
That skill's unit is the call. This one's unit is the session.

## Write the goal labels yourself

**You are the extraction step for the `goal` field.** Read the corpus query output session by session and write each starting intention as you go. Do not hand that field to a script.

This is the one rule that decides whether the output is worth anything, so it is stated before the workflow rather than inside it.

The reason is measured, not stylistic. `scripts/extract_facets.py` runs one API call per session, and no call can see what the other few hundred wrote, so they never converge on shared wording — a 500-session run came back with 487 distinct labels. Worse, each call describes the mechanics it can see rather than the reason behind them: a session whose opening calls read _inspect workflow, read schema, patch graph_ comes back as `update workflow content` instead of `fix a misfiring workflow`. On the `workflows-create` corpus that collapsed debugging and repair from 37 sessions to 4, and it was the most actionable finding in the notebook.

Reading the sessions yourself works because you see every earlier batch as you write the next, so the vocabulary converges. Keep a running list of the labels you have already used and reuse them verbatim.

The scripts still earn their place — see step 4 for what to delegate and what not to.

## Workflow

### 1. Fix the tool and window

Ask which tool, if it wasn't given. Default to 90 days.
Everything downstream keys off the effective tool name, which needs the coalesce below — `$mcp_tool_name` is the current property and `tool_name` is the legacy one, and both are in the data.

### 2. Build the corpus

Sessions that called the target tool, with their opening calls concatenated in order, and **the caller and org selected alongside them**:

```sql
WITH target AS (
    SELECT DISTINCT properties.$mcp_session_id AS sid
    FROM events
    WHERE event = '$mcp_tool_call'
      AND timestamp > now() - INTERVAL 90 DAY
      AND coalesce(nullIf(toString(properties.$mcp_tool_name), ''), toString(properties.tool_name)) = '<TOOL>'
),
sess AS (
    SELECT
        properties.$mcp_session_id AS sid,
        max(if(toString(properties.$mcp_client_user_agent) ILIKE 'posthog/wizard%', 1, 0)) AS is_wizard,
        max(if(toString(person.properties.email) ILIKE '%@posthog.com', 1, 0)) AS is_staff,
        coalesce(nullIf(any(toString(properties.$mcp_consumer)), ''), '') AS consumer,
        coalesce(nullIf(any(toString(properties.$mcp_client_name)), ''), '') AS client,
        coalesce(nullIf(any(toString(properties.mcp_vendor_client)), ''), '') AS vendor,
        coalesce(
            nullIf(any(toString(properties.$mcp_organization_id)), ''),
            nullIf(any(toString(properties.organization_id)), ''),
            '') AS org
    FROM events
    WHERE event = '$mcp_tool_call'
      AND timestamp > now() - INTERVAL 90 DAY
      AND properties.$mcp_session_id IN (SELECT sid FROM target)
    GROUP BY sid
),
organic AS (
    SELECT sid, consumer, client, vendor, org FROM sess WHERE is_wizard = 0 AND is_staff = 0
),
steps AS (
    SELECT
        properties.$mcp_session_id AS sid,
        timestamp AS ts,
        concat(
            coalesce(nullIf(toString(properties.$mcp_tool_name), ''), toString(properties.tool_name)),
            ': ',
            substring(toString(properties.$mcp_intent), 1, 130)
        ) AS step
    FROM events
    WHERE event = '$mcp_tool_call'
      AND timestamp > now() - INTERVAL 90 DAY
      AND properties.$mcp_session_id IN (SELECT sid FROM organic)
      AND coalesce(properties.$mcp_intent, '') != ''
)
SELECT
    substring(toString(s.sid), 1, 8) AS sid,
    multiIf(
        o.consumer != '', concat('consumer:', o.consumer),
        o.client != '', o.client,
        o.vendor != '', o.vendor,
        'unattributed') AS caller,
    o.org AS org,
    arrayStringConcat(arraySlice(arrayMap(x -> x.2, arraySort(groupArray((s.ts, s.step)))), 1, 4), ' >> ') AS opening
FROM steps AS s
INNER JOIN organic AS o ON s.sid = o.sid
GROUP BY s.sid, caller, org
ORDER BY sid
LIMIT 400
```

Four or five calls is the working default. The opening carries the starting point; later calls describe the tool's own work and pull goals toward the action.

**Select the caller and the org here, not later.** `extract_facets.py` reads the header row and carries any column between `sid` and `opening` through to its output. Fetching either as a separate query means hand-transcribing a few hundred lines with nothing checking them — a step that has already gone wrong once.

The two columns answer different questions and neither substitutes for the other. The caller is the software making the call. The org is the customer it makes the call for.

`$mcp_organization_id` is the reliable one. On a 90-day `workflows-create` corpus it was set on every session, against roughly two thirds for the caller properties. Coalesce it onto the legacy unprefixed `organization_id`, the same way the tool name coalesces onto `tool_name`.

**Keep the org as an id, never a name.** The id is opaque and the analysis only needs identity, not labels. A column of customer names turns a shareable notebook into a customer-identifying document, and nothing downstream needs it.

**Take every corpus count from this query, never from an earlier sizing query.** Sizing runs get done on a different window while you are deciding how much to bite off, and those numbers then look authoritative when you write the notebook intro. A run stated 520 sessions and 507 organic in its header when the actual window held 237 and 233, because the sizing query had used 30 days and the corpus used 14. Nothing catches this: both numbers are real, they just describe different things. Read the totals off the corpus and the caller-share query, and reconcile them against each other before writing any prose.

Check whether the row cap bit. `execute-sql` returns at most 500 rows, so a corpus that comes back at exactly 500 is a sample and must be labelled as one; anything below the cap is the complete population.

### 3. Check the skew before extracting anything

Run a quick frequency pass over the intents first.
MCP corpora are routinely dominated by one automated program — a setup wizard, a scheduled scout, a CI job — and a taxonomy built without noticing that describes one script rather than a user population.

```sql
SELECT toString(properties.$mcp_intent) AS intent, count() AS n
FROM events
WHERE event = '$mcp_tool_call'
  AND timestamp > now() - INTERVAL 90 DAY
  AND coalesce(nullIf(toString(properties.$mcp_tool_name), ''), toString(properties.tool_name)) = '<TOOL>'
GROUP BY intent ORDER BY n DESC LIMIT 40
```

If one program dominates, split the corpus and say so in the notebook.
Report both shares — the automated one is a real finding, not noise to hide.

**Split on the caller, never on intent keywords.** The caller is recorded; the keyword filter is a guess about what an agent chose to write, and it fails in both directions. On the `notebooks-create` corpus, an intent filter missed 88 wizard sessions and wrongly flagged 21 others. Seventy-one of the misses landed in the taxonomy and distorted five separate intentions — including `document an incident`, where 11 of 13 sessions turned out to be the wizard writing its own report.

Caller identity is spread across four properties, and you have to check all of them, in this order:

| Property                 | Identifies             | Example values                                                            |
| ------------------------ | ---------------------- | ------------------------------------------------------------------------- |
| `$mcp_client_user_agent` | PostHog's own programs | `posthog/wizard; version: 2.45.0; program: nextjs`                        |
| `$mcp_consumer`          | the upstream surface   | `posthog-code` (Desktop), `slack`, `plugin`, `posthog-cli`                |
| `$mcp_client_name`       | the calling agent      | `claude-code`, `cowork`, `claude-ai`, `cursor-vscode`, `codex-mcp-client` |
| `mcp_vendor_client`      | vendor identity        | `ClaudeCode`, `Cowork`, `ClaudeAI`                                        |

**Checking only `$mcp_client_name` will mislead you.** The setup wizard sets none of client, consumer, or vendor — it identifies itself solely in the user agent. Group by client alone and every wizard session collapses into an `unknown` bucket that looks like missing instrumentation — on a wizard-heavy tool that bucket is the largest row in the table.

```sql
max(if(toString(properties.$mcp_client_user_agent) ILIKE 'posthog/wizard%', 1, 0)) AS is_wizard
```

Attribution is not complete. About 37% of `$mcp_tool_call` volume project-wide sets none of the four, so build the classification as "known caller X" versus "unattributed" rather than assuming absence means anything. Cross-tabulate any new caller rule against the obvious alternative before trusting it — that cross-tab is what exposed the 88.

Also consider excluding staff, since internal dogfooding and customer usage are usually different distributions:

```sql
max(if(toString(person.properties.email) ILIKE '%@posthog.com', 1, 0)) AS is_employee
```

### 4. Extract a facet per session

Two ways to do this, and they are not interchangeable. **Read the corpus yourself for the `goal` field.** The script is faster and fine for the other facets.

Both were run over the same 500 `workflows-create` sessions, so this is measured rather than argued:

|                      | `scripts/extract_facets.py` + canonicalize | Reading the corpus yourself      |
| -------------------- | ------------------------------------------ | -------------------------------- |
| Model                | `gpt-4.1-mini`                             | whichever model runs the skill   |
| Wall clock           | 72s extract + 20s canonicalize             | six read-and-write rounds        |
| Distinct labels      | 159 (3.1 sessions each)                    | **105 (4.8 each)**               |
| `data_touched`       | agrees with hand on **90%**                | —                                |
| `destination`        | agrees with hand on **78%**                | —                                |
| Debugging and repair | 1 label, 4 sessions (0.8%)                 | **4 labels, 37 sessions (7.4%)** |

That last row is why the default is what it is. "A fifth of a create tool is maintenance" was the most actionable finding in the `workflows-create` notebook, and the scripted extraction loses it almost entirely — a session whose opening calls are _inspect workflow, read schema, patch graph_ comes back as `update workflow content` rather than `fix a misfiring workflow`. The model describes the mechanics it can see and does not infer the reason behind them.

**The structural cause is worth understanding, because no prompt fixes it.** Each session is a separate API call that cannot see what the other 499 wrote, so they cannot converge on shared wording. Raw output was 487 labels for 500 sessions. `canonicalize_intentions.py` recovers most of that, but it can only merge wordings — it cannot recover an altitude the extraction never reached. Reading the corpus yourself works because you see every previous batch as you go.

**Use the script for speed, then fix the goals.** The facets it gets right are the mechanical ones; extract with it, canonicalize, then read the goal labels and correct the altitude. `gpt-4.1-mini` matches [`intent_generation.py`](../../backend/intent_generation.py), which already uses it for the closest existing job, so the two stay comparable.

```bash
export OPENAI_API_KEY=$(op read "$(grep -E '^OPENAI_API_KEY=' .env.local | cut -d= -f2- | tr -d '"')")

python scripts/extract_facets.py corpus.txt facets.jsonl \
    --tool workflows-create --facet destination \
    --values email,slack,webhook,person_property,unclear

python scripts/canonicalize_intentions.py facets.jsonl facets_canonical.jsonl --target 70
python scripts/audit_intentions.py facets_canonical.jsonl
```

`canonicalize_intentions.py` is not optional after a scripted extraction. It shows every distinct label to the model at once — the thing the per-session calls could not do — takes back a vocabulary, dedupes that vocabulary against itself, and assigns by embedding similarity. Skipping it leaves you with roughly one label per session.

`.env.local` holds 1Password references rather than literal secrets, so the `op read` step is not optional. `timeout` does not exist on macOS — wrapping `op read` in it produces a 36-character error string that looks like a resolved key. Check the resolved value's shape, never its length.

Doing it yourself is still right for a small corpus, or when no key is available. Work in batches of roughly 50 sessions and emit one record per session.

For each session, produce:

| Field                     | Always | Meaning                                                     |
| ------------------------- | ------ | ----------------------------------------------------------- |
| `sid`                     | yes    | session id, carried through unchanged                       |
| `goal`                    | yes    | the starting task: 3-8 words, imperative, generalized       |
| `data_touched`            | yes    | did the session query analytics data before using the tool? |
| _one tool-specific facet_ | no     | the axis that matters for this tool                         |

Pick the third facet from what the tool is for — `notebook_role` (publish / read / track / draft) for notebooks, `destination` for exports, `edit_scope` for mutation tools.
One is usually enough. See [`references/facet-schemas.md`](references/facet-schemas.md) for how to choose and what has already been tried.

Rules that decide whether the output is usable:

- **Generalize.** Two sessions doing the same kind of work must produce the _same_ goal string. If they differ only by which company or metric was involved, they are the same goal.
- **Recover the starting point, not the action.** "create a notebook" is the action. "investigate an error spike" is the goal. If a goal names the tool, it is wrong.
- **Never write a customer, company, project, product, person, or app name into any field.** These appear constantly in intents. Write "a mobile app", not the app's name. This is not optional — the notebook is shareable, and the existing cluster snapshot already leaks customer names into its labels.

### 4b. Audit the intentions for drift

The generalize rule is the one extraction breaks, and it breaks quietly. One job ends up under two labels, the intention count inflates, and every share deflates. Nothing errors.

```bash
python scripts/audit_intentions.py facets.jsonl
```

This embeds each distinct intention with `text-embedding-3-small` and prints the closest pairs. It merges nothing — semantic closeness is not a merge instruction, and you have to read each pair and decide whether it is one job or two.

On the `workflows-create` run, 105 intentions produced three pairs above 0.80:

| Similarity | Pair                                                                   | Verdict                                                                                 |
| ---------: | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
|      0.819 | `investigate a product error` / `investigate a production error`       | same job, merge                                                                         |
|      0.805 | `build a support automation` / `build a support reply automation`      | same job, merge                                                                         |
|      0.805 | `build a recurring digest email` / `build a recurring digest to slack` | one job, two destinations — keep split, or the destination facet stops meaning anything |

Two merges out of 105, touching 8 sessions. Small, but the point is that a run without the audit reports 105 intentions when the honest count is 103, and nothing in the pipeline would have said so.

**Watch the ceiling, not just the flag count.** Highest similarity here was 0.819, so a threshold of 0.86 flags nothing and reads exactly like a clean result. The script prints the closest pairs regardless, so an empty flag list is never mistaken for verified.

This is also the only embedding step in the skill, and it is deliberately not doing the grouping — see "Why the grouping is by hand" in [`references/notebook-assembly.md`](references/notebook-assembly.md).

### 5. Publish the notebook

Full cell-by-cell recipe, including the facets cell and the sandbox gotchas: [`references/notebook-assembly.md`](references/notebook-assembly.md).

Shape:

1. `notebooks-create-markdown` — title and a short method paragraph
2. `notebooks-configure-compute` — 4 cores / 8 GB, **before** the first Python cell
3. `notebooks-add-cell` (sql) — the corpus, one row per session with its caller and org
4. `notebooks-add-cell` (sql) — caller share for the tool, over `$mcp_tool_call`, so the automated traffic you filtered out stays visible
5. `notebooks-add-cell` (python) — the facets inlined once, keyed on `sid`, as `(sid, starting_intention, theme, data_touched, <third facet>)`
6. `notebooks-add-cell` (sql) — starting intentions, a `GROUP BY` over that frame
7. `notebooks-add-cell` (sql) — themes, the same frame one level up, listing the intentions each theme holds
8. `notebooks-add-cell` (sql) — intentions per org, joined to the corpus on `sid`, carrying the theme
9. `notebooks-add-cell` (sql) — the concentration checks from step 6
10. `notebooks-add-cell` (markdown, optional) — example sessions resolved to trace URLs, per "Linking an intention to real sessions"
11. `notebooks-add-cell` (markdown) — findings, and the skew correction from step 3

**Cells 6 and 7 carry no caller and no org.** The taxonomy states what people came to do. Mixing a population column into it answers two questions in one table and answers both worse. Cell 8 is where the two dimensions meet, and it is the only place they should.

**Key the Python frame on `sid`. Do not pre-aggregate it.** One row per distinct facet combination is smaller, and it is a dead end. With a few hundred orgs mostly holding one session each, adding the org to the combination key inflates it to roughly the session count anyway. Keyed on `sid`, every later cut becomes a join to the corpus frame, the caller stops being duplicated into the literal, and the transcription no longer involves counting.

Pick the `dataframe_name` when you add the cell. `notebooks-update-cell` takes only `code`, so renaming a published frame later means deleting the cell and adding it again.

### 6. Check concentration before writing findings

Run this over the corpus frame, on both dimensions, and let the answer decide whether a deeper analysis exists to do:

```sql
WITH per_org AS (SELECT org, count(*) AS n FROM corpus GROUP BY org),
ranked AS (SELECT org, n, row_number() OVER (ORDER BY n DESC) AS rk FROM per_org)
SELECT
    (SELECT count(*) FROM corpus) AS sessions,
    count(*) AS orgs,
    round(100.0 * sum(case when rk <= 1 then n else 0 end) / (SELECT count(*) FROM corpus), 1) AS top1_pct,
    round(100.0 * sum(case when rk <= 10 then n else 0 end) / (SELECT count(*) FROM corpus), 1) AS top10_pct,
    sum(case when n = 1 then 1 else 0 end) AS orgs_with_one_session
FROM ranked
```

**The check has to be allowed to say no.** On a 90-day `workflows-create` corpus the top org held 5.6% of sessions, the top ten held 21.2%, and roughly three fifths of orgs appeared exactly once. That is a long tail. No dominant-customer story exists, the split below does not run, and the honest move is to report the shape and continue.

**When one caller or a few orgs do dominate, split the taxonomy rather than describing it.** A large share is not a finding by itself. What changes a product decision is whether that population wants different things from everyone else. Recompute the intentions table for the segment and for the remainder, put them side by side, and read the differences.

Rough triggers, as a starting point rather than a rule:

- one caller above 40% of organic sessions
- the top ten orgs above half of them
- any single org above 10%

One case deserves the split even when every share looks unremarkable: a theme whose org list is one org repeating. That is one customer's workflow rather than a pattern, and the session count hides it completely.

### 7. Read the result honestly

- The **starting intentions** are the finding. Themes are a hand-assigned rollup over them; say so, and keep the intentions table available for a reader who disagrees with a grouping.
- **Read the per-org table for whether a theme is a pattern or one customer.** Twenty sessions from twenty orgs and twenty from one org are different findings, and the theme table alone cannot tell them apart.
- **Read the caller table for whether one population exists or several.** A theme dominated by one surface is a different product than a theme spread across all of them.
- An intention or theme under 5 sessions is not a finding. The code suppresses them and reports the count.
- Report shares against the corpus you actually labelled, not the raw session count.
- Distinct-intention count against session count is a useful shape signal on its own: near 1:1 means every session is a one-off, which is a different product problem from a few intentions repeating.
- If the largest intentions are all one automated program, the honest headline is "this tool is mostly automation", not a user taxonomy.

## Linking an intention to real sessions

Every corpus row carries `$mcp_session_id`, and that reaches AI observability. **The join runs from the trace side, not the tool-call side** — `$mcp_tool_call` carries no `$ai_trace_id` at all, but `$ai_generation` carries `$mcp_session_id`.

```sql
SELECT
    toString(properties.$mcp_session_id) AS sid,
    toString(properties.$ai_trace_id) AS trace_id,
    count() AS generations
FROM events
WHERE event = '$ai_generation'
  AND timestamp > now() - INTERVAL 30 DAY
  AND coalesce(toString(properties.$mcp_session_id), '') != ''
  AND toString(properties.$mcp_session_id) IN (SELECT toString(sid) FROM <your corpus>)
GROUP BY sid, trace_id
```

Build the link as `https://us.posthog.com/project/<project_id>/ai-observability/traces/<trace_id>`. The query params the UI adds when you click through are optional.

**Coverage tracks the population worth studying.** On the `notebooks-create` corpus, roughly half of organic external sessions resolved to a trace, about three quarters of organic staff sessions, and effectively none of the wizard sessions. Automated traffic is invisible here; the sessions you actually want are the ones that resolve.

### What the trace does and does not contain

Every generation attached to those sessions was `$ai_product = 'mcp'`, `$ai_span_name = 'execute-sql'`. The trace shows **PostHog's own server-side query work during the session** — what the agent asked the warehouse and what came back.

That is genuine evidence for an intention: a concrete example of what the work looked like. It is not the user's conversation.

**There is still no user message.** `$mcp_intent` is prose the _agent_ wrote about its own call, and the person's actual words stay in the harness — Claude Code, Cursor, the chat client — which never sends them to PostHog. If someone asks for "the user's message", a trace link is the nearest honest substitute, and worth naming as a substitute rather than passing off as the thing asked for.

`/mcp-analytics/sessions` takes no session id, so there is no per-session deep link on the MCP side either. The trace link is the only clickable route into one session.

### Two query traps that silently invert the answer

Both produced confidently wrong numbers on this corpus before being caught.

- **`properties.$mcp_session_id IN (...)` lets nulls through.** Rows with no session id pass the filter, so a composition query returns the project's entire `$ai_generation` volume while reporting `uniqExact(...) = 0` sessions. Always guard with `coalesce(toString(properties.$mcp_session_id), '') != ''` first.
- **`LEFT JOIN` plus `countIf(joined_col != '')` counts every row as matched.** An unmatched join yields `''`, not null, and the comparison behaves unexpectedly — it reported every session as traced where the true figure was about half of them. Use set membership (`countIf(sid IN (SELECT ...))`) instead of a join for coverage counts.

Sanity-check any coverage number by computing it a second way before publishing it.

## Privacy

Adapted from Clio's layered defense, and each layer is load-bearing:

1. Proper nouns are stripped at extraction, not later.
2. Clusters below 5 sessions are suppressed.
3. Cluster labels are synthesized from member goals, never copied from one member's intent.
4. Raw `$mcp_intent` strings never enter the notebook — only goals and aggregates.

Layers 3 and 4 are the ones people skip. Verbatim intents carry customer names, project ids, and run ids straight into a shareable document.

## Related skills

- [`exploring-mcp-intent-clusters`](../exploring-mcp-intent-clusters/SKILL.md) — per-call intent clusters, tool routing, discoverability
- [`exploring-mcp-sessions`](../exploring-mcp-sessions/SKILL.md) — the individual sessions behind a cluster
- [`exploring-mcp-tool-quality`](../exploring-mcp-tool-quality/SKILL.md) — per-tool error rates and latency
- [`improving-mcp-tools`](../improving-mcp-tools/SKILL.md) — acting on what the taxonomy shows
