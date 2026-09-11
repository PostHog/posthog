# The report channel: `emit_report` / `edit_report`

A scout's output is the **report channel**: it does its research, then authors (or edits) a full inbox `SignalReport` directly, 1:1.
This reference is the contract for that channel: the tools, their fields, when to author vs. edit, and the two behaviors to design around (it isn't idempotent, and the pipeline may later rewrite what you authored).

The channel is granted via the skill's frontmatter `allowed_tools` — **every scout should list `emit_report` / `edit_report` there**; see [Granting the tools](#granting-the-tools).

> **Tool names vs. opt-in strings.** The callable MCP tools are
> **`scout-emit-report`** and **`scout-edit-report`** — those are the names you
> invoke. The bare `emit_report` / `edit_report` (underscored) used throughout this doc and below
> are the **opt-in strings** you list under `allowed_tools`; they are not callable tool names. And
> like every `scout-*` tool, **both report tools require the current `run_id`** (the run
> you're executing in) on every call — omitting it fails validation.

## Author vs. edit

| You have…                                                                                                       | Use                                                                                                             |
| --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| A finished, well-formed finding no existing report covers — file it **1:1** with full control of title/summary. | `emit_report`                                                                                                   |
| New information about a report that already exists (one you authored last run, or a pipeline report).           | `edit_report`                                                                                                   |
| An observation you can't yet stand behind as a standalone report.                                               | Neither — write a scratchpad entry and keep investigating (see [`dedupe-and-memory.md`](dedupe-and-memory.md)). |

The report bar is high: author only when you'd stand behind the report as a standalone inbox item a human will act on.
A weak or partial observation belongs in the scratchpad, where a future run (with more evidence) can pick it up — not in the inbox.

## `emit_report` — author a full report

Judges the report for safety, then persists it at the judged status.

| Field                       | Type                    | Notes                                                                                                                                                                                                                                                                                                                                          |
| --------------------------- | ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run_id`                    | string, required        | The current run's id — the run you're executing in, same as every `scout-*` tool.                                                                                                                                                                                                                                                              |
| `title`                     | string, ≤300, non-empty | The inbox headline. One specific, quantified line.                                                                                                                                                                                                                                                                                             |
| `summary`                   | string                  | The report body prose — one tight passage a busy human can act on: a **quantified hook** (what's happening, with numbers), the **pattern** that makes it signal rather than noise, the suspected-cause **hypothesis**, and the **recommendation**. Cite entities inline as markdown links so the reader pivots straight to source (see below). |
| `evidence`                  | list, 1–50              | Each `{description, source_id}`. Becomes a bound signal row backing the report. `source_id` is the citable entity id. Hard cap of **50** — summarize/trim before calling; a longer list fails validation before the report is judged or persisted.                                                                                             |
| `actionability_explanation` | string                  | One sentence justifying the actionability call below.                                                                                                                                                                                                                                                                                          |
| `actionability`             | enum                    | `immediately_actionable` / `requires_human_input` / `not_actionable`. You make this call — the channel does not re-research it.                                                                                                                                                                                                                |
| `already_addressed`         | bool, default `false`   | Set when the underlying issue is already handled and you're filing for the record.                                                                                                                                                                                                                                                             |
| `metrics`                   | list, ≤6, optional      | Typed impact measurements the inbox shows as tiles. The report's full set. Each `{metric_id, title, kind, query, role?, value?, value_at?, series?, value_format?, unit?, caption?}`. See _Measuring impact_ below.                                                                                                                            |
| `charts`                    | list, ≤20, optional     | Queries the inbox draws on the report — the report's full set, replacing any it already had. Each `{chart_id, title, query, caption?, size?}`. See _Attaching charts_ below.                                                                                                                                                                   |
| `suggested_prompts`         | list, ≤3, optional      | Follow-up prompts the inbox offers above the report's `Ask AI` box (questions to ask, or next-step actions to request), each ≤200 characters and all distinct. See _Suggesting follow-up prompts_ below.                                                                                                                                       |

**Cite each entity as a link, not a bare id.** In `summary` and in `evidence` descriptions, write
the entity you name as a markdown link: reuse the url the returning tool attached (`_posthogUrl`
and friends), else build one with `generate-app-url`, and keep the bare id when neither reaches
the entity itself. Two spots stay plain text, because the inbox renders them as text: `title`, and
the summary's first line, which the inbox lifts out as the card headline. The harness prompt
(_Linking what you reference_) carries the full rule.

**Section labels are where a Slack thread splits.** A destination with "Post reports as a thread" on posts a short lead in the channel and each later section as a reply.
A heading (`## Evidence`) and a bold label on a line of its own (`**Evidence**`) both mark a section, so write the outline you want the reader to get and either form works.
Leave a blank line above each label, since a label the line above runs onto is part of that paragraph rather than a new section.

**Status is decided for you, from safety × actionability:**

| Safety judge | `actionability`          | Resulting status | Surfaces in inbox? |
| ------------ | ------------------------ | ---------------- | ------------------ |
| safe         | `immediately_actionable` | `READY`          | yes                |
| safe         | `requires_human_input`   | `PENDING_INPUT`  | yes                |
| safe         | `not_actionable`         | `SUPPRESSED`     | no                 |
| unsafe       | (any)                    | `SUPPRESSED`     | no                 |

The result tells you what happened: `report_id` (always set when a report was persisted — **even when suppressed**, so you can edit or dedup against it), `report_status` (the birth status — `ready` / `pending_input` / `suppressed` — the field is named `report_status` in the response, not `status`), `emitted` (true only when it actually surfaced — `READY` / `PENDING_INPUT`), `safety_explanation`, and `skipped_reason` (set only when a preflight gate stopped the call before any report was created — the AI-data-processing / source-enabled gates that govern every scout write).

### Measuring impact

`metrics` carries the typed measurements that tell a reader what the observation changes, and how many people it reaches.
The inbox shows each one as a tile: the figure with its unit, the title, the window the query covers, and a small trend strip.
Use one `primary` metric for the key observation, and `supporting` metrics for the facts around it.

**Omit a metric you cannot measure honestly.**
A weak number is worse than none.
One support ticket and a single migration crash tell the reader nothing.
Nor does a rate over a handful of attempts, or a count with no person context.

| Field          | Type                | Notes                                                                                                                                                                           |
| -------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `metric_id`    | string, required    | Your own slug (lowercase letters, numbers, `_`, `-`, starting with a letter or number), ≤100 characters. Unique within the report, and the key a later edit refreshes it under. |
| `title`        | string, required    | What was observed, and for whom, in one line: `Users who hit "Not found" opening a shared chat link`, not a label such as `Users affected`. ≤200 characters.                    |
| `kind`         | enum, required      | What the value measures. See _Choosing the kind_ below.                                                                                                                         |
| `query`        | object, required    | The bounded live query behind the figure. See _Keeping the query live and bounded_ below.                                                                                       |
| `role`         | enum, default       | `primary` for the report's key observation, else `supporting` (the default). At most one `primary` per report.                                                                  |
| `value`        | number, optional    | A snapshot you measured in this run. Optional cached fallback only. Pair it with `value_at`.                                                                                    |
| `value_at`     | timestamp, optional | When you measured `value`. ISO-8601 with a timezone, and not in the future.                                                                                                     |
| `series`       | list, optional      | Trailing per-bucket values from the same run, oldest first, ≤14 points. Part of the snapshot, so it needs `value` and `value_at`.                                               |
| `value_format` | enum, default       | How to print the figure: `count`, `percentage`, `percentage_scaled`, `duration`, `currency`, or `number` (the default).                                                         |
| `unit`         | string, optional    | Short suffix that completes the figure, ≤40 characters. See _Keeping semantics separate from formatting_ below.                                                                 |
| `caption`      | string, optional    | Only what the tile cannot show, ≤500 characters. See below.                                                                                                                     |
| `comparison`   | object, optional    | Legacy. Leave it unset.                                                                                                                                                         |

A primary affected-users metric and a supporting rate, as they arrive in `metrics`:

```json
[
  {
    "metric_id": "people-hitting-not-found",
    "title": "Users who hit \"Not found\" opening a shared chat link",
    "kind": "affected_users",
    "role": "primary",
    "value": 412,
    "value_at": "2026-06-18T09:00:00Z",
    "value_format": "count",
    "unit": "users",
    "series": [38, 41, 55, 60, 49, 52, 58, 61, 57, 63, 66, 71, 68, 74],
    "query": {
      "kind": "InsightVizNode",
      "source": {
        "kind": "TrendsQuery",
        "dateRange": { "date_from": "-13d" },
        "interval": "day",
        "series": [
          {
            "kind": "EventsNode",
            "event": "$pageview",
            "math": "dau",
            "properties": [
              { "type": "event", "key": "$pathname", "operator": "icontains", "value": "/shared/" }
            ]
          }
        ]
      }
    }
  },
  {
    "metric_id": "shared-link-failure-rate",
    "title": "Shared chat links that fail to open",
    "kind": "error_rate",
    "value_format": "percentage_scaled",
    "unit": "failure",
    "caption": "Production only, excluding internal users.",
    "query": {
      "kind": "InsightVizNode",
      "source": {
        "kind": "TrendsQuery",
        "dateRange": { "date_from": "-13d" },
        "interval": "day",
        "series": [
          { "kind": "EventsNode", "event": "shared_link_opened", "math": "total" },
          { "kind": "EventsNode", "event": "shared_link_failed", "math": "total" }
        ],
        "trendsFilter": { "formula": "B / A", "aggregationAxisFormat": "percentage_scaled" }
      }
    }
  }
]
```

#### Choosing the kind

Choose by what the reader will ask, not by what the source makes easy.

| Kind                | Use it for                                                                                                                                                                                                        | Query shape                                                                             |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `affected_users`    | Anything a person experiences: a captured exception with person context, a dead click, a rage click, a failed request on a surface, a broken URL.                                                                 | Exactly one series, `math: "dau"`. `value_format: "count"`.                             |
| `affected_sessions` | A source that establishes sessions but not people.                                                                                                                                                                | Exactly one series, `math: "unique_session"`. `value_format: "count"`.                  |
| `occurrences`       | Noise, and backend failures: a report asking the team to stop reporting something as an error, a Temporal, Celery, or job exception with no person on the event, or a volume counter such as tool calls per week. | Total count. `value_format: "count"`.                                                   |
| `error_rate`        | A flow that fails.                                                                                                                                                                                                | Two series plus one formula such as `B / A`, with percentage formatting.                |
| `conversion_rate`   | A flow that stalls.                                                                                                                                                                                               | Same shape as `error_rate`.                                                             |
| `duration`          | A source that measures time.                                                                                                                                                                                      | `value_format: "duration"`, `unit` of `ms` or `s`, and a non-negative snapshot.         |
| `revenue`           | A source that measures money.                                                                                                                                                                                     | `value_format: "currency"`, `unit` of an uppercase three-letter ISO code such as `USD`. |
| `custom`            | A measurement that no kind above covers.                                                                                                                                                                          | Still needs a live event or action query.                                               |

**A figure with no event or action query behind it stays in the prose.**
A database statistic, a build time read from another tool, or a number quoted from an external source has no query, so it cannot be a metric.

**A noise report where nobody was hurt takes `occurrences`, never `affected_users`.**

**An `affected_users` metric means distinct PostHog people**, not sessions, events, requests, traces, groups, or the report's signal count.
`affected_sessions` means distinct sessions.
Group math and a formula are refused on both, because the total comes from the series math alone.

#### Keeping the query live and bounded

The query is the source of truth; it runs again every time a reader opens the report.
So attach a query you ran successfully in this session, the same rule the charts carry.

- **One `InsightVizNode` wrapping one `TrendsQuery`.** Any other node kind is refused at write time.
- **Event and action series only.** Every source series must be an `EventsNode` with a non-empty `event`, or an `ActionsNode` with a positive integer `id`. This is what lets the server check a reader's access without an unbounded query fan-out.
- **A relative window that advances with time.** `dateRange.date_from` must be relative (`-13d`, `-30d`), at most 366 days, and `date_to` must be empty. Default to `date_from: "-13d"` with `interval: "day"`, which gives 14 inclusive daily buckets including today. `interval` accepts `second` through `year`.
- **At most 1,000 estimated longitudinal points**, counting the current partial bucket. One hourly series over roughly six weeks fits.
- **Exactly one output series.** Without a formula that means exactly one source series. A rate may combine up to 10 source series with exactly one formula. A breakdown and compare mode are both refused, because either can multiply the output at run time.
- **Keep the filters that reproduce the observation**, so the figure measures the thing the report describes.

**Consumers own the display.** The report derives two shapes from the stored query: `BoldNumber` for the whole-window `aggregated_value`, and `ActionsBar` for the longitudinal buckets.
The display you author does not control how the report draws the metric.
Run the total-value shape when you measure a snapshot, because a bar or line response gives no whole-window total.
Never sum distinct-user buckets, since one person can appear in several.

#### Keeping semantics separate from formatting

`kind` says what the metric measures. `value_format` says how to print it.

- A non-currency `unit` is one lowercase word that completes the figure, because the report prints it next to the number: `users`, `sessions`, `events`, `runs`, `calls`.
- For a rate, name what the share means: `failure` for an error rate, `conversion` for a conversion rate. `%` is redundant and is dropped.
- Use `percentage` for percentage points (`34` means 34%) and `percentage_scaled` for 0–1 ratios (`0.34` means 34%).
- **A percentage query must set `aggregationAxisFormat` to exactly the same value as `value_format`.** A missing or numeric axis format is invalid.

#### Titling and captioning

The tile prints the figure, the unit, the title, and the window together, so never state one fact twice across them.

Leave `caption` empty unless it carries something the reader needs and cannot see:

- a filter that narrows the count (`Production only, excluding internal users`),
- why a longer window was needed,
- a caveat on the data (`Person context is missing on about a third of these events`).

A caption that restates the title, the unit, or the window is noise.
The strip shows at most the trailing 14 buckets, so a window longer than 14 days needs the caption that explains it.

#### Snapshots are optional cached fallbacks, not estimates

A snapshot keeps an inbox list read cheap.
It never replaces the required live query.

- Send a snapshot only for a value you measured in this run. Zero is a real measurement; null means unavailable.
- A `count` snapshot and series must be non-negative whole numbers. A rate snapshot must sit inside its format's range (0–100 for `percentage`, 0–1 for `percentage_scaled`).
- **Never author a snapshot-only or queryless row.** Those shapes are legacy or malformed, and the server always redacts them.
- **Leave `comparison` unset.** The server does not yet keep an adjacent comparison window live, so an authored comparison is stored and never shown.

A reader opening the report refreshes the metric, which replaces `value`, `value_at`, and `series`, and clears `comparison`.
Listing reports never executes a metric query: a row carries the metric metadata and any readable cached snapshot, but no query definition.

#### A reader may see the tile without its data

A metric snapshot is measured without a requesting user, while a report read is authorized as the viewer.
When the server cannot prove the two are equivalent, the metric stays in the response with its data-bearing fields redacted.

- **A cohort reference, including a nested one, hides the metric from every reader.** There is no cohort object access policy to prove access against, so this is an intentional safety limit rather than a display bug. Keep a cohort filter out of a metric query.
- A reader can also lose the query, the snapshot, or both for access reasons you cannot see while authoring: a property restriction, a missing token scope, an action they cannot read, or an unfamiliar filter shape.

So a metric is not a way to deliver a number to a reader who could not run the query themselves.
Keep the figure the report's argument depends on in the `summary` prose, where every reader gets it.

#### Caps, and what an edit does

At most one `affected_users` metric, and 60,000 characters of query JSON across the report.
Prefer the few measurements that change the decision.

**`metrics` on an edit is the report's whole set, not an addition**, exactly like `charts`.
Omit the field to keep the metrics the report has, send the complete replacement list to change them, or send `metrics: []` to clear them.
Re-send a `metric_id` with a newer query or snapshot to refresh that metric.
Read the report first (`inbox-reports-retrieve` returns its metrics) when you mean to add one.

Every metric title, caption, snapshot, and query goes before the safety judge, the same as the report prose.

### Attaching charts

`charts` puts the data next to the claim, so a reader sees the move instead of taking the number on trust.
Worth it when the _shape_ is the point — a trend that broke, a distribution that shifted, a funnel step that collapsed.
A chart restating one number the summary already gives is noise; just write the number.

| Field      | Type             | Notes                                                                                                                                                                                                  |
| ---------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `chart_id` | string, required | Your own slug (lowercase letters, numbers, `_`, `-`). How the summary points at the chart, and the key a later edit refreshes it under. Unique within the report.                                      |
| `title`    | string, required | Heading above the chart.                                                                                                                                                                               |
| `query`    | object, required | An `InsightVizNode`, `DataVisualizationNode` (a `HogQLQuery` source, plus `display` and `chartSettings` for a graph), or `SavedInsightNode` (by `shortId`). Any other `kind` is refused at write time. |
| `caption`  | string, optional | One line on what to look at.                                                                                                                                                                           |
| `size`     | enum, optional   | `small` / `medium` / `large`. Leave it out unless the default looks wrong — the inbox sizes a chart from its query (a big single number gets a short box, a retention grid a tall scrolling one).      |

A trends chart and a graph built from SQL, as they arrive in `charts`:

```json
[
  {
    "chart_id": "exceptions-daily",
    "title": "Exceptions per day",
    "caption": "The step up starts on 18 June.",
    "query": {
      "kind": "InsightVizNode",
      "source": {
        "kind": "TrendsQuery",
        "dateRange": { "date_from": "2026-06-01", "date_to": "2026-07-02" },
        "interval": "day",
        "series": [{ "kind": "EventsNode", "event": "$exception", "math": "total" }],
        "trendsFilter": { "display": "ActionsLineGraph" }
      }
    }
  },
  {
    "chart_id": "exceptions-by-type",
    "title": "People affected, by exception type",
    "query": {
      "kind": "DataVisualizationNode",
      "source": {
        "kind": "HogQLQuery",
        "query": "SELECT exception_type, uniq(distinct_id) AS people FROM ... GROUP BY exception_type ORDER BY people DESC"
      },
      "display": "ActionsBar",
      "chartSettings": { "xAxis": { "column": "exception_type" }, "yAxis": [{ "column": "people" }] }
    }
  }
]
```

**A graph from SQL needs its axes named.** Setting `display` without `chartSettings` draws an empty box; `chartSettings.xAxis.column` and `chartSettings.yAxis[].column` say which columns of the result are which.
Omit `display` altogether and the node renders the result table, which reads better than a chart for a handful of rows.

**Only the node's `kind` and its serialized size are checked on write.** A well-formed node of an allowed kind carrying a broken query is stored without complaint, then fails to draw when a reader opens the report, and nothing reports that back to the scout.
So a scout should attach a query it has already run in the same session, or point at an insight that already exists via `SavedInsightNode`, rather than composing a node from memory.
This is the single most useful thing to reinforce in a scout body that leans on charts.

**A chart query must not carry anything executable.** HogVM `bytecode` (what conditional formatting compiles to), a nested `HogQuery`, and `sendRawQuery` are each refused with a 400 wherever they sit in the node, because a chart renders data rather than running code in the reader's session.
A nested `SuggestedQuestionsQuery` is refused the same way, for cost rather than execution: its runner calls an LLM, so a chart carrying one buys a completion every time a reader opens the report.
A query over a warehouse connection is fine as long as it goes through HogQL: keep `connectionId`, drop `sendRawQuery`.
So a direct-warehouse query you ran with the raw-SQL bypass has to be rewritten before it can be attached.

**Placement comes from the summary.** A markdown link with a `chart:` target — `[Daily signups](chart:signups-drop)` — draws the chart at that point in the body; a chart you never reference still renders, after the prose.
Reference each chart once: a repeated reference reads as pointing back at the chart, not as asking for a second copy of it.
Two references in one paragraph sit side by side, so put a pair you want compared in a paragraph of their own.
A reference inside a code span, a table cell, or a heading has no room to draw — its chart falls to the end of the report instead.

**The summary has to read without the charts.** A report can also be delivered to Slack, where each reference degrades to the plain label it was given and the charts follow the prose as images rather than sitting inline.
Only `InsightVizNode` and `SavedInsightNode` charts render there, at most three per report with referenced charts first; a `DataVisualizationNode` chart shows only in the inbox.
"Signups fell 60% over the week" survives that; "the chart below shows the drop" leaves a Slack reader with nothing.

**Pin the window** to absolute dates wherever the node supports it, so a reader opening the report days later sees the data you wrote about rather than whatever a relative range resolves to then.

**`charts` on an edit is the report's whole set, not an addition.**
It replaces what the report had, the way `summary` replaces the summary — so send every chart you want kept, and re-send an id under a newer window to refresh that chart.
Leave `charts` out entirely and the report keeps the ones it has; read the report first (`inbox-reports-retrieve` returns its `charts`) when you mean to add to them.
Send `charts: []` to take every chart down, for when the finding has moved on and the old chart would now mislead.
Cap is **20 charts per report** (and a combined query-size budget), which is far more than most reports should use. Each chart runs its query when the report is opened, so attach the ones that carry the argument rather than everything you looked at: three charts a reader studies beat a dozen they scroll past.

### Suggesting follow-up prompts

`suggested_prompts` are prompts the inbox offers above the report's `Ask AI` box: follow-up questions, and next-step actions the reader can send as a request.
Clicking one fills the box with it; nothing is sent on the click, so the reader can send it as written or edit it first.
You did the research and know which threads you left open and what should happen next, so this hands the reader that knowledge instead of leaving them to invent a prompt from an empty box.

Optional, and worth it only when you can name a prompt worth an agent run.
Write none rather than pad to the cap — a report with no suggestions looks exactly as it did before.

**Ask what your research left open, not what it already answered.**
A question the summary answers spends an agent run restating the report.
Good ones widen the finding (who else is affected, since when, what changed), test a hypothesis you could not, or ask for the next step you did not have the standing to take.

**Offer the action your report recommends, so acting on it is one click.**
The prompt reaches an agent run that can investigate, carry out the report's recommendation, and work the report itself — its work log and its state — so a good action prompt names the concrete work: "Create the alert the report recommends, then mark this report resolved".
Fold in "mark this report resolved" only when the action completes in place — an action that lands as a pull request must not resolve the report, because a caller resolve closes the report's open PR and the merge resolves the report on its own.
Suggest only actions your report's own recommendation makes concrete; leave anything a human should weigh first (deleting data, changing a flag serving live traffic) as a question instead.

**Write each prompt as the reader would send it, in their words** — a question they would ask or a request they would make — and make each one stand alone: the prompt reaches an agent that gets the report as context but not your run, so it can't point at "the above" or "the second chart".

**`suggested_prompts` on an edit is the report's whole set, not an addition.**
It replaces what the report had, the way `summary` replaces the summary, so re-send every prompt you want kept.
Leave the field out and the report keeps the ones it has; send `suggested_prompts: []` to take them down.
Rewriting `summary` on an edit does not clear them for you, so send the new set (or `[]`) in the same call.
The research pipeline does clear them when it rewrites a report it re-researches, since the prompts were written against the prose it replaces.

Cap is **3 prompts per report**, each **≤200 characters**, and duplicates are refused.

### Opening a draft PR (autostart)

A surfaced, immediately-actionable report can open a draft PR automatically — the same autostart path the pipeline uses.
It's opt-in per report via three more `emit_report` fields; supply them only when the report is a concrete, fixable issue you'd want a PR for:

| Field                  | Type        | Notes                                                                                                                                                                       |
| ---------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `repository`           | string      | `"owner/repo"` targets that repo; **omitting it** falls back to free-form selection; the `NO_REPO` sentinel opts out. See _Choosing a repository_ below.                    |
| `priority`             | `P0`-`P4`   | Required for a PR. Pair with `priority_explanation`.                                                                                                                        |
| `priority_explanation` | string      | Required when `priority` is set.                                                                                                                                            |
| `suggested_reviewers`  | list of obj | Reviewers to consider, each `{github_login?, user_uuid?}` (at least one per entry; see the section below). A PR opens only if at least one clears their autonomy threshold. |

**Choosing a repository.** Prefer `owner/repo` whenever you can say where a fix would land, including on a `requires_human_input` report — a repository does not open a PR by itself, it is what lets a person open one from the inbox later.
Omit the field when your team has several repositories and you can't tell which one, so selection can find it; that is the slow path on a many-repo team, since it spawns a selection sandbox.
Keep `NO_REPO` for the rare report where nothing under version control could change, such as a staffing finding or a data question with no artifact.
A skill body, a config file, and a doc all live in a repository, so "not code" is not the test.

Full repo selection only runs when you signal PR intent — an explicit `repository`, or both `priority` and `suggested_reviewers`.
A report that supplies none of these just surfaces in the inbox: no repo sandbox, and no PR.
It still gets a repo target when its own text links exactly one repository the team has connected on GitHub, so someone reading it can click Create PR.
That inferred target is for a person to act on — it never opens a PR by itself, and rewriting the report's title or summary to link a different connected repository moves it.
Adding a qualifying reviewer later is a person asking for the PR, so the report can open a draft one from then on.
Autostart itself still no-ops unless the report is `immediately_actionable`, has a repo + priority, and a reviewer qualifies — so these fields are safe to omit for an informational report.

## Choosing `suggested_reviewers` — how a report gets assigned to a human

`suggested_reviewers` is **not just a PR gate** — it is the **primary way a report gets routed to the right person internally**.
The inbox orders by `is_suggested_reviewer`, so a reviewer's own reports float to the top of _their_ inbox; a report with the right reviewer reaches that human even when **no PR** is involved.
**Set it whenever you can name a plausible owner — including on informational `requires_human_input` reports**, not only PR-bound ones.
A report with no reviewer just sits in the shared inbox hoping someone grabs it.

Each entry identifies one reviewer by **`github_login`**, **`user_uuid`**, or both:

- **`github_login`** — a **bare, lowercase GitHub login** (e.g. `octocat`, not `@OctoCat`).
  Internal assignment matches it against each user's linked GitHub login by exact, lowercased comparison, so a mis-cased handle, an `@`-prefix, a display name, a CODEOWNERS **team** slug, or an email won't set `is_suggested_reviewer` for anyone (autostart's PR-selection path is more lenient, but the assignment path is not).
- **`user_uuid`** — a **PostHog user UUID**.
  The server resolves it to that org member. It wins if you also pass a `github_login`.
  Use this whenever your evidence already names a PostHog user. It works without a linked GitHub account.
  A `user_uuid` that is not an org member of this team is rejected, so it never silently drops.

So you have two routes to a reviewer.
If you already hold a PostHog user UUID, prefer passing it as `user_uuid` — it's the most reliable.
Otherwise resolve a `github_login`, cheapest source first:

1. **Scratchpad cache.** A `reviewer:<domain>:<area>` entry you (or a sibling run) recorded before — reuse it.
   Fastest path, and the reason the caching step at the end of this list exists.
2. **Inbox precedent.** `inbox-reports-list` for a similar/related report on the same surface (same `source_product`, plus a free-text `search` for the area), then `inbox-reports-retrieve` / `inbox-report-artefacts-list` to see who comparable reports were routed to.
   Reuse that reviewer for the same area — the safest general recipe, available to every scout.
3. **CODEOWNERS / git** (only if the scout has a repo checkout).
   `.github/CODEOWNERS` for the owning path, or the last `git log` author for the file.
   Neither usually hands you a usable login directly: CODEOWNERS entries are often **team** slugs (`@your-org/team-name`) and `git log` gives a name + email — both must be resolved to an **individual** GitHub login before you write the reviewer (a team slug or an email won't match any user).
4. **`scout-members-list`** — the in-run roster lookup, for the cold-start case where the cheaper paths above don't resolve an owner.
   It returns this project's members, each with `user_uuid`, email, name, and a resolved `github_login`. Pass `search=` to narrow the result. Match the owner and route with `user_uuid`.
   The org-scoped `org-members-list` / `org-member-get-github-login` tools are **not available in a scout run** — a scoped-team token can't reach the org-nested endpoint, so don't build a scout's reviewer recipe around them.

**If you can't confidently identify a reviewer, leave `suggested_reviewers` empty** — the report still surfaces for a human to grab.
**Never guess a handle**: a wrong login mis-assigns the report (or silently fails to assign), which is worse than leaving it open.
And remember `edit_report` can set reviewers on a report later — so a report that surfaced routed to no one isn't stuck; once you resolve an owner, edit it in (which also re-runs autostart).

**Cache for next time.** After you confidently tie an area to an owner, write a `reviewer:<domain>:<area>` scratchpad entry with the bare lowercase login so the next run — and sibling scouts — route faster.
The fleet's reviewer map should compound over time.

## `edit_report` — update an existing report

Rewrite `title`/`summary`, append evidence or a note, set `suggested_reviewers`, and/or replace `metrics` / `charts` / `suggested_prompts` on a report that already exists.
Pass `run_id` (the current run) and `report_id`, plus at least one of `title`, `summary`, `append_note`, `append_evidence`, `suggested_reviewers`, `metrics`, `charts`, `suggested_prompts`.
An edit that supplies content (`title`, `summary`, `metrics`, `charts`, `suggested_prompts`, `append_note`, `append_evidence`, or a reviewer `reason`) passes the same safety judge as `emit_report`; an unsafe edit is rejected whole and the report keeps what it had.

`edit_report` can target **any** of the team's inbox reports — not just ones a scout authored.
That makes it the right tool when a later run learns something about a report the pipeline (or another scout) created.
Rules of good behavior:

- Use **`append_evidence`** for a new observation that a reader can check.
  It takes the same `{description, source_id}` items as `emit_report`, and each one lands in the report's evidence rail as a bound signal, so the report's `signal_count` and `total_weight` grow with it.
- Use **`append_note`** for commentary — a reading of the report that adds nothing to check, such as the owning team already knowing, or a deploy having fixed it.
  Send both in one call when an observation needs a reading alongside it.
- **A recovery is a note, not evidence.** `signal_count` and `total_weight` only grow, and both feed the inbox ranking, so evidence that an issue is over would rank the report as stronger.
- **At the cap, the note is the channel that still lands.** Emit plus every append share the report's **50** evidence rows, and the grouping pipeline can raise the count too, so a long-lived report can fill up. An append past the cap is rejected and the report keeps what it had.
- Prefer these additive fields over rewriting `title`/`summary` on a report you didn't author.
  A note is additive and audit-friendly (it carries your scout as the author); a rewrite silently overwrites a human- or pipeline-authored headline.
- **Don't fight an in-flight pipeline.** A report the summary/research workflow is mid-run on can have its fields overwritten under you.
  If a report is actively being worked, append a note rather than rewriting.
- **Take the questions down when you replace the prose they answer.** Rewriting `summary` leaves the report's `suggested_prompts` in place, and they were written against the summary you just replaced — send a fresh set in the same call, or `[]` to clear them.
- **Use `suggested_reviewers` to rescue an unrouted report.** Setting reviewers (same `{github_login?, user_uuid?}` shape as `emit_report`) replaces the report's reviewer list and re-runs autostart — so a report that surfaced routed to no one can be assigned to an owner you resolved later, and a now-actionable report with a repo + priority can open a draft PR.
  An empty list is a no-op (it never clears existing reviewers).

## Finding "the report I made last time"

There is no scout-specific report search — use the **vanilla inbox tools** the scout already has.
Before authoring, list the team's existing reports so you reconcile against one instead of filing a duplicate:

- `inbox-reports-list` — filter by title/summary free-text (`search`), `status`, `source_product`, or your own `task_id`; newest-updated first.
- `inbox-reports-retrieve` — fetch a single report by id (use the `report_id` you stashed in the scratchpad last run).

## Dedup: the retry is covered, the near-duplicate is not

`emit_report` carries an emit key, so resending a call that timed out returns the report the first one authored (`idempotent_replay` true) rather than a twin.
The key is the `idempotency_key` you pass, or the report's own content when you pass none, and it is scoped to your run.
Pass one when a retry might reword the report, since a reworded report is a different content key.

That barrier covers the transport failure and nothing else.
A report on a topic an earlier run already filed is a fresh emission with a fresh key, so the cross-run dedup is still two-sided and the scout owns it:

1. **Before authoring**, `inbox-reports-list` for a prior report on the same topic.
   Found one?
   `edit_report` it instead of authoring a new one.
2. **After authoring**, write a `report:<domain>:<entity>` scratchpad entry recording the `report_id` so the next run finds it (via `inbox-reports-retrieve`) without a title-search guess.
   (This is the report-channel member of the scratchpad key-prefix vocabulary — see [`dedupe-and-memory.md`](dedupe-and-memory.md).)

`edit_report` has no such barrier: **never retry an `edit_report` call that may have succeeded**, since a transport error after the write commits, retried, appends a second note.
If you're unsure whether an edit landed, `inbox-reports-retrieve` to check before retrying.

## The pipeline may rewrite what you authored (accepted)

An authored report is a first-class `SignalReport` that coexists with pipeline reports.
When future signals consolidate around the same topic, the pipeline may **re-promote and re-research the report, overwriting your authored `title`/`summary`**.
This is accepted behavior, not a bug — there is no pin.
Don't author a report assuming your exact prose is immutable; author the finding, and let the inbox stay the source of truth for how it's currently framed.
Your durable record of "I filed this" is the `report:` scratchpad entry and the `report_id`, not the title text.

## Granting the tools

In the scout's `SKILL.md` frontmatter, list the report tools under `allowed_tools`:

```yaml
allowed_tools:
  - emit_report
  - edit_report
```

**Every scout needs this** — a scout that omits it falls back to a deprecated legacy channel (weak `emit-signal` findings a pipeline consolidated) and can't write reports at all.
Don't author new scouts without the opt-in; if you find an existing scout missing it, add it and rework the scout's Decide section onto this contract.
The canonical fleet runs on this channel; `signals-scout-anomaly-detection`'s `references/report-contract.md` keeps a worked, surface-specific shape (its notebook write-up + embedded-chart recipe).
Add a short body section telling the scout what's report-shaped for its surface.
Keep it lean — the field-level detail lives here (and in the harness prompt), not in the body.

**Rollout posture:** for a chatty or high-stakes new scout, start in **dry-run** (`emit=false` on its `SignalScoutConfig`) so it runs and logs what it _would_ author without writing to the inbox.
Inspect via `scout-runs-retrieve`, calibrate, then flip `emit=true`.
The channel files a full inbox item on the first hit, so the cautious loop is worth it when in doubt.
