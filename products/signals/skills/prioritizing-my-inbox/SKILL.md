---
name: prioritizing-my-inbox
description: >
  Present a personal, ranked shortlist of the PostHog Inbox reports the current user is most
  likely to care about right now. Calls `inbox-reports-for-me` once for the server's personal
  ranking (built from the user's activity summary, the inbox ranking model, suggested-reviewer
  routing, ownership, pull request state and recency) and shows the top N (25 by default) with
  a reason and a next step for each. Falls back to building the ranking from
  `inbox-reports-list` pools when that tool is not available. Use when the user says "let's look
  at my inbox", "what's in my inbox for me?", "my top 10 inbox reports", "what should I look at
  today?", or asks to re-rank, focus, or filter that list. For browsing, filtering, drilling
  into, or acting on a single report, use `inbox-exploration`.
---

# Prioritizing my inbox

The inbox on an active project holds hundreds or thousands of open reports.
The default list order puts the user's suggested reports first, then sorts by status and update time.
That order is not a personal ranking.

`inbox-reports-for-me` returns the personal ranking that PostHog builds for the caller.
One call gives the ranked list, a tier, a reason and a next step for each report.
Show that list.
Do not rebuild or re-score it: the order must match what other PostHog surfaces show the person.

## Parse the request

- **N**: "top 10", "my top 5", "25 things". Default to 25. The tool accepts at most 50. Above 50, say so and ask whether they want a filter instead.
- **Focus**: a theme, product, or keyword ("only anomaly stuff", "error tracking"). It becomes the `focus` parameter.
- **Filters**: "skip digests", "not the scout fleet ones", "nothing with a PR yet", "things I can fix", "just new ones". Apply them to the returned list (see [Re-ranking](#re-ranking)).

## Get the ranking

```json
inbox-reports-for-me
{ "limit": 25 }
```

Add `"focus": "<their words>"` when they asked for a focus.
A focus or `refresh` call builds a new list, and a build can take tens of seconds.
Tell the person that it can take a moment before you call.

Read these fields from the response:

- `results`: the ranked entries. Each has `rank`, `tier`, `reason`, `next_step`, `matched`, and a compact `report` (id, title, priority, status, `_posthogUrl`, `ranking`, pull request state).
- `cached` and `generated_at`: whether the list came from storage, and when it was built.
- `personalized`: `false` means PostHog had no activity summary for the person, so the order uses routing and the model only.
- `folded`: report ids that the ranking folded into a result (digest series, duplicates), with the reason.
- `ranked_count` and `candidates_considered`: how much of the inbox the ranking covers.

### When to fall back

Use [references/pool-and-score.md](references/pool-and-score.md) when one of these is true:

- The tool is not in your tool list, or the call returns 404. The personal ranking is not available to this person yet.
- The response has `personalized: false` and no `results`.

When `personalized` is `false` but `results` has entries, show the list.
Say in one line that it is not personal yet, and offer to focus it on two or three topics the person names.

If the response is empty and `personalized` is `true`, run the setup check in `inbox-exploration` before you say the inbox is empty.

## Present the list

Lead with one line: personal or not, the list age from `generated_at` (for example "built 40 min ago"), and how many reports the ranking covered.
Then the list, in the order the tool returned.
For each entry:

```text
1. [<title>](<_posthogUrl>) · P2 · tier: needs you · ready, PR #123 open (approved)
   Why you: <reason>
   Model: action 9.1x · fix 4.7x
   Next: <next_step>
```

- **Title link** from `report._posthogUrl`. Always include it.
- **Priority, tier, state**: `priority`, `tier`, `status`, and the pull request with its review state.
- **Why you**: the `reason`, shortened to one line when it is long. Do not invent a different reason.
- **Model**: lifts for `action` and `fix` from `report.ranking.predictions` (or `open` when the others are missing). Say "unscored" or "stale score" rather than a blank. The lifts are model estimates, so present them as relative likelihood, not odds.
- **Next**: the `next_step`.

Keep each entry to three or four short lines.
After the list, add at most three lines:

- What the ranking folded in (from `folded`) and what your filters removed.
- How to adjust: "say 'focus on anomaly scoring', 'skip digests', 'top 10 things I can fix', or 'refresh'".
- An offer to drill into any item. Hand off to `inbox-exploration` for drilling in, acting, or resolving.

Use a table instead of the list when the person asks for one, or when N is small and they want a scan.

## Re-ranking

Reuse the list you hold when you can.
Call the tool again only for a focus, a refresh, or more rows.

| They say                        | Do                                                                                                                              |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| "More on X" / "focus on X"      | Call again with `focus: "X"`                                                                                                    |
| "Refresh" / "anything new?"     | Call again with `refresh: true`                                                                                                 |
| "Only X"                        | Keep the entries whose title, `reason` or `matched` names X. If few are left, call with `focus`                                 |
| "Skip digests" / "skip scout Y" | Drop entries by title pattern or scout name                                                                                     |
| "Things I can fix"              | Keep entries with no pull request and a high `fix` lift                                                                         |
| "What's waiting on me"          | Keep entries whose `tier` or `reason` says they wait on the person, `pending_input` reports, and approved pull requests         |
| "Just new ones"                 | Keep entries whose `reason` or `matched` marks them as new. Read a report with `inbox-reports-retrieve` when you need its dates |
| "Ignore the model"              | The server order includes the model. Use the fallback with `model_multiplier` 1.0, and say so                                   |

A filter can leave fewer than N entries.
Then call again with a larger `limit` (up to 50) and the same `focus`, and filter again.
A larger `limit` without `refresh` reads the stored list, so it does not cost a new build.

## Guardrails

- This skill reads only. Do not claim, dismiss, resolve, or run actions on a report from the list without the person asking for that report by name. Use `inbox-exploration` for those steps.
- A model prediction says what may happen. A high `fix` probability does not mean the report is fixed. Read `status` and the pull request fields for that.
- Never quote the activity summary back at length. It is personal context for ranking. Mention the theme a report matched, not the profile.
- Do not call `refresh` or `focus` again and again in one conversation. Each call is a new build, and the server limits builds per person.
