# Finding what stands out in a trend

For "explain this chart" when the user names no change.
Read the series yourself and pick the moments worth a chapter.
Work from the numbers in the query result, not from a picture of the chart.

## Before you look

- **Leave out a period that has not ended.** When the chart's range runs to today, the last point is still counting and reads low. Mention it, but do not judge it against complete points.
- **Use the median as the typical level.** One extreme point moves an average but not a median.
- **Sparse series.** When 30% or more of the points are zero, judge against the non-zero points only, and say how many points are not zero.
- **Cumulative charts.** A cumulative line only rises, so every split looks like a change of level. Run the same query as a line of each period's value and pick the moments from that, then use those dates for the chart you explain.

## Moments worth a chapter

Look for these, in this order of how much they usually matter:

1. **A lasting change of level.** Find the point where the median before and the median after differ most, with at least three complete points on each side. It is worth a chapter when the level after is 1.4 times the level before or more, or 0.7 times or less. Judge any peak against the level on its own side of the change. A change in the last one or two points is a peak, a low point or the latest point, and it is too early to say whether it lasts.
2. **Peaks.** A point well above the typical level: more than 1.8 times it, and clear of the normal spread. Include the neighbours that are still more than halfway up. A "peak" wider than about a fifth of the chart is a change of level, not a peak. Keep the two biggest.
3. **Empty stretches.** Two or more points in a row below a tenth of the typical level. This is usually tracking that stopped or an outage, not behavior. Check for a deploy or an SDK change before you explain it any other way.
4. **A single low point.** Below 40% of the typical level, and clear of the normal spread.
5. **A weekly rhythm.** On a daily chart with two weeks or more, compare the median weekend day with the median weekday. Outside 0.6 to 1.5 times, say so once, so the dips do not read as problems.
6. **The latest complete point.** Compare it with the level the chart is at now. With a weekly rhythm, compare it with the same kind of day.

Cap the story at about five chapters.
Order dated moments by date, and put the weekly rhythm and the latest point last.
A chart with nothing on this list is a finding too: say the level is steady, and stop.

[`compare_to_prior_periods.py`](../scripts/compare_to_prior_periods.py) checks whether a moment is normal variance for its day of the week or hour.
