# Report template

Keep the report short. Lead with the total, then the biggest drivers, then the recommendations.
Every amount is in dollars. The numbers below are invented and only show the shape.

```markdown
**Self-driving spend, Oct 1 to Oct 28: $1,240**
Signals $910, scouts $330. Oct 27 and 28 are provisional.

| Source                     | Reports | Acted on | Spend | Per report |
| -------------------------- | ------- | -------- | ----- | ---------- |
| Error tracking: new issues | 410     | 12%      | $380  | $0.93      |
| Support tickets            | 220     | 41%      | $260  | $1.18      |
| Replay scanners            | 390     | 18%      | $170  | $0.44      |
| 3 other sources            | 140     | 30%      | $100  |            |

| Scout             | Runs | Runs with no reports | Spend |
| ----------------- | ---- | -------------------- | ----- |
| Product analytics | 670  | 96%                  | $140  |
| Error tracking    | 330  | 58%                  | $110  |
| 2 other scouts    | 120  | 70%                  | $80   |

**By day:** weekdays $45 to $60, weekends about $20. One spike on Oct 14 ($140) came from replay scanners.

**Recommendations**

1. Turn off new-issue signals from error tracking and keep spiking issues. Saves up to about $380 a month. 88% of these reports were never acted on. I can apply this.
2. Run the product analytics scout daily instead of hourly. Saves about $130 a month. 96% of its runs found nothing. I can apply this.
3. Set a spend limit of $900 a month after these changes. Self-driving pauses for the rest of the month if it is reached. Set it on the billing page.
```

After the report, ask which recommendations to apply.
Apply only the ones the user confirms, one at a time.
