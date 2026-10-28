# Report template

Keep the report short. Lead with the total, then the biggest drivers, then the recommendations.
Every amount is in dollars.
The numbers below are invented and only show the shape.
The recommendations in it are examples of the format, not advice: build each one from the project's own data.

```markdown
**Self-driving spend, Oct 1 to Oct 28: $1,240**
Signals $910, scouts $330. Oct 27 and 28 are provisional.

| Source                         | Reports | Resolved¹ | Spend | Per resolved |
| ------------------------------ | ------- | --------- | ----- | ------------ |
| Error tracking: new issues     | 410     | 38        | $380  | $10.00       |
| Support tickets                | 220     | 41        | $260  | $6.34        |
| Replay scanners                | 390     | 6         | $170  | $28.33       |
| Error tracking: spiking issues | 35      | 0         | $40   | none yet     |
| 3 other sources                | 140     | 22        | $60   | $2.73        |

| Scout             | Runs | Runs with no reports | Resolved¹ | Spend |
| ----------------- | ---- | -------------------- | --------- | ----- |
| Product analytics | 670  | 96%                  | 1         | $140  |
| Error tracking    | 330  | 58%                  | 9         | $110  |
| 2 other scouts    | 120  | 70%                  | 3         | $80   |

**By day:** weekdays $45 to $60, weekends about $20. One spike on Oct 14 ($140) came from replay scanners.

**Recommendations**

1. Turn off inbox findings for the two replay scanners with the most findings and no resolved reports. Saves about $110 a month. I can apply this.
2. Run the product analytics scout daily instead of hourly. Saves about $130 a month. 96% of its runs found nothing. I can apply this.
3. Set a spend limit of $1,200 a month after these changes. Self-driving pauses for the rest of the month if it is reached. Set it on the billing page.

¹ Reports take about 14 days to resolve. 60% of the reports in this period are newer than that, so the resolved counts will rise. The recommendations above use only reports older than 14 days.
```

Add the footnote only when most reports in the period are newer than 14 days.
Put a `¹` after "Resolved" in the table headers when you add it.

After the report, ask which recommendations to apply.
Apply only the ones the user confirms, one at a time.
