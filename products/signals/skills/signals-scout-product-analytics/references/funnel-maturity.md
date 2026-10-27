# Scoring a funnel only from mature entrant windows

How to read conversion rates for mature entrant windows with `query-funnel`.
The maturity rule itself is in the body: an entrant window that ends at E is mature only when E + the conversion interval is at or before the cutoff.
This file covers the query that measures those windows without cutting off late conversions.

## Why a `steps` query over the entrant window is wrong

The funnel `dateRange` filters the events of every step, not only the entry step.
A `steps` query with a `dateRange` of one entrant week ignores every conversion after the week ends.
A person who enters on the last day of the week then gets less than one day to convert, whatever the saved interval is.
Do not score a funnel from a `steps` query bounded to the entrant window.

## The trends-mode query

Trends mode groups entrants by entrant period, and counts each entrant's conversions inside the conversion interval, also after the period ends.

- Copy the saved funnel's `series`, `funnelOrderType`, `funnelWindowInterval`, `funnelWindowIntervalUnit` and filters into the query. Do not change the measured flow.
- Set `funnelsFilter.funnelVizType: trends` and `interval: week` (use `day` only for a daily cadence).
- Set a `dateRange` that ends now. Start it at the beginning of an entrant period that is at least one conversion interval, the buffer and N+2 entrant periods before now. Then the latest mature point and N mature baseline points remain after you drop the immature points, and the first point is a full period.
- Pass `output_format: "json"`. The default optimized output shows only rates and no entrant counts.
- Each result holds `days`, `data` (conversion %), `reached_from_step_count` (entrants) and `reached_to_step_count`, with matching indexes.
- Each point is one entrant period. Score only the points whose entrant period ended at least one conversion interval, plus the buffer, before now. Use the older mature points as the baseline.
- With `interval: day`, compare a point only to baseline points on the same weekday.
- Use `reached_from_step_count` for the volume gate, the steady-denominator check and the report evidence.

## Step-to-step rates

Each trends point is the first-to-last rate, and `query-funnel` has no step selector.
Build each step rate from prefix funnels instead, with the same trends query:

- Step 1 → 2: `data` of the prefix funnel of steps 1..2.
  Do not query a one-step prefix, because `query-funnel` rejects a funnel with fewer than two steps.
- Step k-1 → k, for k of 3 or more: query the prefix funnels of steps 1..k-1 and 1..k. Divide `reached_to_step_count` of the longer prefix by that of the shorter prefix at the same index.
  For this rate, the denominator is `reached_to_step_count` of the shorter prefix. Use it for the volume gate and the evidence. Skip a point where it is zero.
- Prefix rates hold only when `funnelOrderType` is `ordered` or `strict`. For an `unordered` funnel, score only the first-to-last rate.

## Funnels this method cannot score

- **Exclusions.** In trends mode, one fully excluded attempt removes that person's failed entries from every period in the `dateRange`. Older baseline points have more later attempts, so their conversion can be too high. Do not author a decline for a funnel with `exclusions` from trends results.
- **Optional steps.** A step marked `optionalInFunnel` is valid only in a `steps` funnel, so the trends query fails. Do not remove the optional setting, because that changes the measured flow. Do not fall back to a `steps` query bounded to the entrant window.

Name such a flow as unscored, with the reason, in the watchlist entry and the run summary.

## Worked example

A saved ordered funnel `Signup → project created → first event`, with a 14-day conversion interval and a weekly cadence. Now is Wed 24, and weeks start on Monday.

- The cutoff is Wed 24 minus 6 hours. The newest mature week is Mon 1 – Sun 7, because Sun 7 + 14 days ends on Sun 21. The week Mon 8 – Sun 14 matures only after Sun 28.
- With N = 4 baseline weeks, start the `dateRange` on a Monday at least 14 days, 6 hours and 6 weeks before now, and end it now.
- Run the prefix funnel `Signup → project created` and the full funnel in trends mode with `output_format: "json"`.
- Read the points for weeks that start Mon 1 and earlier. Drop the points for Mon 8, Mon 15 and Mon 22, which look low only because their entrants are still converting.
