---
name: prioritizing-my-inbox
description: >
  Give the current user a personal, ranked shortlist of the PostHog Inbox reports they are most
  likely to care about right now. Reads their stored personal ranking first, with one
  `inbox-reports-list` call (`view=for_you`, `sort=personal`), and keeps its order and reasons.
  Uses `inbox-reports-for-me` for a fresh or focused list, and builds a ranking by hand from the
  activity summary and the ranking model's lifts only when no stored ranking applies or the user
  asks for custom weights. Use when the user says "let's look at my inbox", "what's in my inbox
  for me?", "my top 10 inbox reports", "what should I look at today?", or asks to re-rank, focus,
  or filter that list. For browsing, filtering, drilling into, or acting on a single report, use
  `inbox-exploration`.
---

# Prioritizing my inbox

The inbox on an active project holds hundreds or thousands of open reports.
PostHog builds a personal ranking for each person on a schedule, from their activity summary, the ranking model's scores, and what waits on them.
`inbox-reports-list` with `sort=personal` serves that stored ranking in one call.
Start there.
Build a ranking yourself only when the stored one does not apply, or the person asks for something it cannot give.

## Parse the request

- **N**: "top 10", "my top 5", "25 things". Default to 10. Above 50, warn that the tail gets thin and ask whether they want a filter instead.
- **Filters**: "only error tracking", "just P0 and P1", "nothing older than a week". Pass them as list filters (`source_product`, `priority`, `search`, `created_after`) in the same call.
- **Focus**: "focus on anomaly stuff". A soft focus changes the order, so it needs a new build. See [Other routes](#other-routes).
- **Window**: add `created_after` only when the person names a window. A generic "what should I look at" request takes no window, because older reports can still need attention.

## Step 1: Read the stored ranking

```json
inbox-reports-list
{
  "view": "for_you",
  "sort": "personal",
  "limit": 10
}
```

Never pass `ordering` with this call: an explicit `ordering` replaces `sort`, and you lose the stored ranking.
Filters narrow the rows, and the rows that are left keep the stored order.
This read never builds a ranking, never calls a language model, and never gathers candidates, so it is fast.

Read three things in the response:

- **`ranker`**. `personal` means the stored ranking ordered the page.
  Any other value (`priority`, `open`, `action`, `fix`, or null) means no stored ranking applied, and the page is in the recommended order.
  Do not call that page personal. See [Other routes](#other-routes).
- **`ranking_id`**. Keep it from the first page.
  For the next page, pass the same `view`, `sort`, filters, and `limit`, with `offset` and this `ranking_id`, so a rebuild between calls does not reorder the pages.
  The response's `next` link does not carry `ranking_id`, so do not follow it as it is.
- **Per-row `personal_tier` and `personal_reason`**.
  They are set on each report the language model ranked: `top`, `worth_a_look`, or `later`, with a short reason.
  After the ranked reports come the reports the ranking folded in, then every other report in the recommended order.
  A row the language model did not rank has null tier and reason, even when the stored ranking placed it.
  `inbox_merge_key` is the row's position in that combined order, from 0.

The stored ranking is only as new as its last build.
A report created after the build sits after the ranked reports until the next scheduled build.

## Step 2: Present the list

Keep the returned order.
You can point out a row that looks done, such as an already merged pull request or `already_addressed: true`, but do not move it without saying so.
Do not replace the order with your own score.

Lead with one line on the source: "From your personal ranking" when `ranker` is `personal`, else say that no personal ranking applied and the list is in the recommended order.
Then the list, in order.
For each report:

```text
1. [<title>](<_posthogUrl>) · P2 · 1d · ready, PR #123 open (approved)
   Why you: <personal_reason>
   Model: action 9.1x · fix 4.7x
   Next: review and merge the PR
```

- **Title link** from `_posthogUrl`. Always include it.
- **Priority, age** (from `updated_at`, or `created_at` for new ones), **state** (`status`, `work_state`, the PR and its review state, who owns it if someone else does).
- **Why you**: `personal_reason`, shortened if it is long. When it is null, say why the row is there instead: suggested reviewer, claimed by them, or waiting on their input. If none applies, say "no personal reason".
- **Model**: lifts for `action` and `fix` (or `open` when the others are missing). Say "unscored" or "stale score" rather than showing a blank. The lifts are model estimates, so present them as relative likelihood, not odds.
- **Next**: one concrete action. Review a PR, answer a question, claim it, dismiss it, or just read it.

Keep each entry to three or four short lines.
Use a table instead of the list when the person asks for one or N is small and they want a scan.
After the list, add at most three lines:

- Which rows have no personal reason, when the page holds some.
- How to adjust: "say 'focus on anomaly scoring', 'refresh my ranking', or 'only error tracking' to change the list".
- An offer to drill into any item. Hand off to `inbox-exploration` for drilling in, acting, or resolving.

## Other routes

Each of these costs more than the list read. Use one only when the request or the response calls for it, and say which one you used.

| Situation                                                                                              | Do                                                                                                                                                                                                                                    |
| ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ranker` is not `personal`                                                                             | Show the recommended order and say that no personal ranking exists yet. Offer `inbox-reports-for-me` with `wait_seconds` to start a build, or the hand-built ranking in [references/pool-and-score.md](references/pool-and-score.md). |
| The person needs a list newer than the last build ("anything new since this morning?")                 | `inbox-reports-for-me` with `max_age_minutes`, or `refresh: true` with `wait_seconds`. It can take up to 30 seconds.                                                                                                                  |
| A soft focus ("focus on anomaly scoring")                                                              | `inbox-reports-for-me` with `focus` and `wait_seconds`. For a hard filter ("only error tracking"), add the filter to the list call instead.                                                                                           |
| Next steps for the top entries                                                                         | `inbox-reports-for-me` returns them with each entry.                                                                                                                                                                                  |
| Custom weights ("ignore the model", "weight fix chances higher") or ranking by activity-summary themes | [references/pool-and-score.md](references/pool-and-score.md). Say that you built the order yourself.                                                                                                                                  |
| "What's waiting on me"                                                                                 | `inbox-reports-list` with `view: "needs_input"` and `scope: "for_me"`, plus `assignee: "mine"` for their claims.                                                                                                                      |
| The list is empty                                                                                      | Run the setup check in `inbox-exploration` before you say the inbox is empty.                                                                                                                                                         |

## Guardrails

- This skill reads only. Do not claim, dismiss, resolve, or run actions on a report from the list without the person asking for that report by name. Use `inbox-exploration` for those steps.
- A model prediction says what may happen. A high `fix` probability does not mean the report is fixed. Read `status` and the PR fields for that.
- Do not say a list is personal unless `ranker` is `personal`, or you built it with the hand-built flow and said so.
- Never quote the activity summary back at length. It is personal context for ranking. Mention the theme a report matched, not the profile.
