# Choosing facets

A facet is a field extracted per session. Two are fixed, one is chosen per tool.

## The fixed two

**`goal`** — the starting task, 3-8 words, imperative, generalized.
This is the field everything clusters on, so its quality decides the whole result.

The failure mode is writing the action instead of the goal. The session's calls describe what the agent did; the goal is what the person wanted before any tool was chosen.
A goal that names the tool is always wrong.

| Session shows                                         | Wrong (action)             | Right (starting point)           |
| ----------------------------------------------------- | -------------------------- | -------------------------------- |
| queries error events, then creates a notebook         | "create an error notebook" | investigate an error spike       |
| lists flags, checks each one's usage                  | "list feature flags"       | audit feature flag usage         |
| runs the same metric query as last week, writes it up | "write a metrics summary"  | build a recurring metrics report |

The second failure mode is under-generalizing. If two sessions differ only by which company, metric, or app was involved, they are the same goal and must produce the same string. Clustering cannot merge what extraction split.

**`data_touched`** — did the session query analytics data (SQL, insights, events, warehouse) before reaching the tool?

This one earns its place by separating two populations that otherwise look identical: someone analyzing something, and a program mirroring a pre-written result.
In the notebooks run it was the single sharpest discriminator — organic sessions queried data first 63% of the time, wizard sessions essentially never did.

## The third facet

Pick one axis that matters for the tool in question. One is usually enough; a fourth rarely changes any conclusion and costs extraction accuracy.

Good third facets answer "what kind of use is this?" rather than "what happened?":

| Tool shape                      | Facet           | Values                                                                        |
| ------------------------------- | --------------- | ----------------------------------------------------------------------------- |
| document / notebook             | `notebook_role` | publish_findings, read_prior_notes, track_ongoing_work, draft_document, other |
| export / delivery               | `destination`   | share_externally, feed_a_pipeline, archive, inspect_locally                   |
| mutation (create/update/delete) | `edit_scope`    | new_object, tweak_existing, bulk_change, cleanup                              |
| query / read                    | `depth`         | single_lookup, exploratory_scan, recurring_check                              |

Avoid facets that are already recoverable from the events. Harness, error rate, call count, and tool sequence are all in `$mcp_tool_call` — extracting them by hand adds noise and no information.

## What the notebooks run found

`notebooks-create`, 90 days, 500 organic sessions, facets `goal` / `notebook_role` / `data_touched`:

- Top 3 goals were 59% of sessions: recurring metrics digests 33%, analytics and config audits 13.2%, anomaly scout runs 13%. Genuine ad-hoc human analysis was 9.8%.
- `notebook_role` split: publish findings 60.6%, read prior notes 12.8%, track ongoing work 11.4%, draft document 9.6%.
- The read-prior-notes path — recurring reports pulling last run's definitions — was also the path failing 13.7% of the time. That pairing is the kind of thing neither facet finds alone.

The lesson worth carrying: `notebook_role` was invented for that tool and does not transfer. Publishing versus reading is the interesting axis for a document tool and meaningless for an export tool.
Choose the third facet from what the tool is for, not from this table.

## Corpus skew

Both runs of this analysis hit the same problem, from different directions, so expect it.

`notebooks-create` was 93% setup-wizard traffic. The intent-cluster snapshot for the same project was dominated by scheduled scout runs discovering tools.
In both cases the largest clusters described one automated program rather than a population of users.

A keyword filter removes the sessions that name themselves and leaves the rest.
In the notebooks run, "set up a dashboard for a new integration" came back as 11.2% of the supposedly organic corpus and turned out to be wizard traffic whose intents never said "wizard".
The fix is to look at the clusters afterwards and ask whether any of them look like the thing you filtered out — the correction moved the wizard share from 92.4% to about 93%, taking roughly a tenth of the supposedly organic corpus with it.

Staff usage is worth separating for the same reason. In the notebooks run, auditing was 32.9% of PostHog-employee sessions and 4.0% of external ones, and recurring digests inverted it at 32.1% external versus 2.6% staff.
A taxonomy built on dogfooding data optimizes for the wrong thing.
