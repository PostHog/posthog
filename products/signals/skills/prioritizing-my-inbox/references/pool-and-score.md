# Pool and score: build a personal ranking by hand

Use this flow only when the stored personal ranking cannot answer the request:

- The list response's `ranker` is not `personal`, and the person wants a personal order now rather than the recommended order.
- The person asks for a ranking with custom weights, such as "ignore the model" or "weight fix chances higher".
- The person asks to rank by themes from their activity summary that the stored ranking does not use.

It costs several list calls and many tokens, and its order can differ from the ranking the person sees in the app.
Say that you built the order yourself, so the person does not take it for their stored ranking.

## Parse the request

- **N**: default to the number from the request, else 10. Above 50, warn that the tail gets thin and ask whether they want a filter instead.
- **Focus**: a theme, product, or keyword ("only anomaly stuff", "error tracking"). It becomes an extra candidate pool and a boost, not a hard filter, unless they say "only".
- **Exclusions**: "skip digests", "not the scout fleet ones", "nothing with a PR yet".
- **Window**: "this week", "today", "since Monday". In this flow, default to reports created or updated in the last 14 days, because the pools must stay small.
- **Mode**: "things I can fix", "things waiting on me", "just new ones". Each maps to a pool or boost below.

## Step 1: Load the person

```json
activity-summary-get
{}
```

From the response, build an **interest profile**:

- **Themes** with `strength` and `last_seen`. A theme seen in the last 3 days with `strength: high` counts most.
- **Specific terms** from `computed.owned` and `computed.watched`: skill names, flag keys, saved query names, insight and dashboard names. These match reports far better than generic theme words.
- **Products** from `computed.products.works_in` and `computed.pages`. They map to `source_product` and to report topics.
- **Recently asked about** lines in `profile`. A report the person asked about this week is a strong candidate.

Generic words make bad search terms.
On a busy project, `search: "ranking"` can match hundreds of reports because summaries mention ranking in passing.
Prefer terms like an owned skill name, a flag key, or a distinctive phrase from a theme label.

If the call returns `status: not_ready` or a 404, there is no summary for this person.
Say so in one line and continue with the other signals.
The ranking then leans on suggested-reviewer routing, claims, and the model.
Offer to let the person name two or three topics they care about, and use those as the interest profile.

## Step 2: Gather candidates

Report rows are large (often 3 to 4 KB each, mostly the summary), so pull several small pools rather than one big page.
Keep `limit` at 20 or below per call.
Pass `exclude` with ids you already hold to keep later pools fresh.
`exclude` takes at most 100 ids and the API rejects a longer list, so send the 100 you most want to skip (the strongest candidates so far) and dedupe the rest locally.
Pools overlap; dedupe by `id` and remember which pools each report came from.

| Pool                    | Call                                                                                                            | Why                                                                    |
| ----------------------- | --------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| For you                 | `view: "for_you"`, `sort: "recommended"`, `created_after: <window>`                                             | Routed to them, waiting on them, or claimed by them                    |
| Recently updated        | `view: "for_you"`, `ordering: "-updated_at"`, no `created_after`                                                | Older reports with new activity, such as a new PR approval or question |
| Mine                    | `assignee: "mine"`                                                                                              | Work they or their agents already own                                  |
| Theme searches          | `search: "<specific term>"`, `created_after: <window>`, one call per top theme (3 to 5 calls, `limit` 10 to 15) | Personal relevance the routing misses                                  |
| Needs my input (option) | `view: "needs_input"`, `scope: "for_me"`, `created_after: <window>`                                             | Decisions only they can make                                           |

All pools use `inbox-reports-list`.
Do not add project-wide pools such as `view: "actionable"` or a bare `ordering: "-ranking_action"`.
They bring in reports routed to someone else, and the list is for this person.
A theme search is the exception, because it matches their own interests.
Always bound `for_you` and `needs_input` by a window.
`created_after` filters on creation time only, so a report created before the window but updated inside it reaches you only through the recently updated pool.
That pool uses `updated_at` as its window: page it until `updated_at` falls outside the window, and stop after 3 pages.
`assignee: "mine"` takes no window because claims never expire, so it can return hundreds of rows. Keep its default order and read only the first page.
On an active project these views can hold a thousand reports, and the oldest `pending_input` rows carry stale scores that look strong.

The ranking `ordering` values and the `ranking_min_*` filters return 400 for users outside the ranking rollout.
When that happens, use `sort: "recommended"` instead, and read the response's `ranker` field to see which order you got.
Rows still carry `ranking.predictions` when the user can see them, so you can score client-side.

Aim for 60 to 150 unique candidates.
That is enough for a strong top 25 without reading the whole inbox.
A person with few reports of their own gets a shorter list. Return the short list rather than filling it with reports from across the project.

## Step 3: Score

Drop reports with `status` `resolved`, `suppressed` or `failed`, and reports with `work_state: done`.
Keep `failed` only when the person asks what broke.
Then give each candidate a score.
[scoring.md](scoring.md) has the default formula, the reasoning behind each term, and worked examples.
In short:

```text
score = priority_base × model_multiplier × freshness
      + interest_bonus + needs_me_bonus
```

- `priority_base`: P0 5, P1 4, P2 3, P3 2, P4 1, none 1.5.
- `model_multiplier`: from the mean of the `action` and `fix` lifts, only when `ranking.status` is `scored` and `scored_at` is within about 7 days. Otherwise 1.0. A missing lift is unknown, not low.
- `freshness`: favor reports updated in the last 2 days, decay those untouched for 3 weeks.
- `interest_bonus`: match against the interest profile. A title match beats a summary match. A match on a high-strength, recently seen theme beats a stale one.
- `needs_me_bonus`: suggested reviewer, a claim they answer for, `pending_input` routed to them, an approved open pull request.

Then apply judgment:

- **Collapse series.** Scouts that write a daily digest produce near-identical titles ("Weekly checkout health, October 26: …", "Weekly checkout health, October 27: …"). Keep the newest one and note how many older ones you folded in.
- **Collapse duplicates.** Two reports about one issue (often one from a scout and one from a GitHub source, sharing a pull request) take one slot. Link both.
- **Spot work that already landed.** A `pending_input` report can ask for something the person has since shipped. Keep it in the list with "may already be done, resolve?" as the next step. Clearing it is useful.
- **Respect "already handled".** `already_addressed: true`, or a pull request someone else is actively driving, lowers a report unless the person is the reviewer.
- **Keep variety.** If one theme fills more than about half the list, demote its weakest items so the person sees the rest of their world too. Skip this when they asked for that theme only.
- **Promote what is waiting on them.** An approved pull request on their report, or a decision only they can make, often beats a higher-priority item someone else owns.

Present the result in the format from the main skill, with "Why you" naming the theme or owned object each report matched.

## Re-ranking

When the person tweaks the request, reuse the candidates you already hold.
Fetch more only when the tweak needs a pool you do not have (a new theme search, a wider window, held-back reports).
Typical tweaks:

| They say                        | Do                                                                                    |
| ------------------------------- | ------------------------------------------------------------------------------------- |
| "More on X" / "focus on X"      | Add a search pool for X, give X matches a large boost                                 |
| "Only X"                        | Filter to X matches                                                                   |
| "Skip digests" / "skip scout Y" | Drop by title pattern or `scout_name`                                                 |
| "Things I can fix"              | Keep `actionability: immediately_actionable` with no PR, weight the `fix` lift        |
| "What's waiting on me"          | Keep the needs-me reports only (`pending_input` for them, PR approvals, their claims) |
| "Just new stuff"                | Window to the last 1 to 3 days, sort by `created_at`                                  |
| "Ignore the model"              | Set `model_multiplier` to 1.0 and say so                                              |
