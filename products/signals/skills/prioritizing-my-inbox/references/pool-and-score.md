# Fallback: build the ranking yourself

Use this method only when `inbox-reports-for-me` cannot give a list:
the tool is missing, it returns 404, or it returns `personalized: false` with no `results`.
It costs one activity summary call and up to seven `inbox-reports-list` calls, so do not use it when the tool works.

Three inputs decide the rank:

1. **Who the person is right now.** `activity-summary-get` returns their current themes, the objects they own and watch, and the products they work in.
2. **What the model predicts.** Each report row carries `ranking.predictions` with a probability and a lift for `open`, `action` and `fix`.
3. **What the report needs from them.** Suggested reviewer, claims they answer for, `pending_input` status, an approved pull request waiting to merge.

Use your judgment on top of the score: the score finds candidates, you decide the order.

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
Prefer terms like an owned skill name (`anomaly-metrics`), a flag key, or a distinctive phrase from a theme label.

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
| Likely action           | `view: "actionable"`, `ordering: "-ranking_action"`, `created_after: <window>`                                  | What the model thinks someone will act on                              |
| New and likely opened   | `created_after: <last 3 to 7 days>`, `ordering: "-ranking_open"`                                                | Fresh reports worth a look                                             |
| Theme searches          | `search: "<specific term>"`, `created_after: <window>`, one call per top theme (3 to 5 calls, `limit` 10 to 15) | Personal relevance the routing misses                                  |
| Needs my input (option) | `view: "needs_input"`, `scope: "for_me"`, `created_after: <window>`                                             | Decisions only they can make                                           |

All pools use `inbox-reports-list`.
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
- **Spot work that already landed.** A `pending_input` report can ask for something the person has since shipped, for example a tool you just called in Step 1. Keep it in the list with "may already be done, resolve?" as the next step. Clearing it is useful.
- **Respect "already handled".** `already_addressed: true`, or a pull request someone else is actively driving, lowers a report unless the person is the reviewer.
- **Keep variety.** If one theme fills more than about half the list, demote its weakest items so the person sees the rest of their world too. Skip this when they asked for that theme only.
- **Promote what is waiting on them.** An approved pull request on their report, or a decision only they can make, often beats a higher-priority item someone else owns.

## Step 4: Present

Use the list format in [SKILL.md](../SKILL.md#present-the-list), with these changes:

- The lead line names the activity summary version and headline (shortened), the pools, and how many candidates you scored.
- Write **Why you** and **Next** yourself from the strongest score terms.
- Say that you built the ranking in the conversation because the personal ranking was not available.

## Re-ranking in the fallback

Reuse the candidates you already hold.
Fetch more only when the tweak needs a pool you do not have (a new theme search, a wider window, held-back reports).

| They say                   | Do                                                                         |
| -------------------------- | -------------------------------------------------------------------------- |
| "More on X" / "focus on X" | Add a search pool for X, give X matches a large boost                      |
| "Just new stuff"           | Window to the last 1 to 3 days, sort by `created_at`                       |
| "Ignore the model"         | Set `model_multiplier` to 1.0 and say so                                   |
| Anything else              | Use the filters in [SKILL.md](../SKILL.md#re-ranking) on the list you hold |
