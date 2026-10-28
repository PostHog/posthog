# Report template

Keep the report short. Lead with the total, then the biggest drivers, then the recommendations.
Every amount is in dollars.
The numbers and names below are invented and only show the shape.
The recommendations in it are examples of the format, not advice: build each one from the project's own data.

The source and scout tables share their last four columns, so the user can compare a source with a scout:

- **Reports created:** reports in the period. For a source, every report its signals went into.
- **Resolved¹:** the settled rate from "Yield" in queries.md, as a percentage. Write "too new" when there are fewer than 20 settled reports.
- **Spend:** spend in the period.
- **Per resolved:** spend divided by (reports created times the settled rate). Write "too new" when Resolved is.

```markdown
**Self-driving spend, Oct 1 to Oct 28: $1,240**
Signals $910, scouts $330. About $1,330 a month at this rate. Oct 27 and 28 are provisional.

| Source                         | Reports created | Resolved¹ | Spend | Per resolved |
| ------------------------------ | --------------- | --------- | ----- | ------------ |
| Error tracking: new issues     | 410             | 9%        | $380  | $10.30       |
| Support tickets                | 220             | 18%       | $260  | $6.57        |
| Replay scanners                | 390             | 4%        | $170  | $10.90       |
| Error tracking: spiking issues | 35              | 2%        | $40   | $57          |
| 3 other sources                | 140             | 21%       | $60   | $2.04        |

| Scout             | Runs | No result | Reports created | Resolved¹ | Spend | Per resolved |
| ----------------- | ---- | --------- | --------------- | --------- | ----- | ------------ |
| Product analytics | 670  | 96%       | 27              | 4%        | $140  | $130         |
| Error tracking    | 330  | 58%       | 140             | 22%       | $110  | $3.57        |
| 2 other scouts    | 120  | 70%       | 36              | 15%       | $80   | $14.81       |

**By day:** weekdays $45 to $60, weekends about $20. One spike on Oct 14 ($140) came from replay scanners.

**Recommended**

1. Run the product analytics scout every 6 hours instead of hourly. 96% of its runs found nothing, and 4% of its settled reports were resolved. Saves about $125 a month. I can apply this.
2. Turn off inbox findings for the "Checkout errors" replay scanner, and keep the scanner running in Replay Vision. 2 of 120 settled reports were resolved, against 4% for replay scanners and 11% for the project. Saves about $60 a month. I can apply this.
3. Turn off spiking-issue signals from error tracking, and keep new and reopened issues. 2% of settled spiking-issue reports were resolved, against 9% for new issues. Saves about $43 a month. I can apply this.
4. Pause the 2 scouts that created and edited nothing this month: "Weekly digest" and "Docs links". Saves about $25 a month. I can apply this.

**Worth a look**

5. Low-priority support tickets from email: 5% of settled reports were resolved, against 18% for support tickets overall. No setting selects them, but research instructions can tell research to skip them. The saving cannot be estimated in advance. I can apply this.
6. New error tracking issues opened 60 pull requests and 9 merged. A priority threshold of P2 instead of P3 would stop the lowest-priority ones. The saving is not measured yet. Change "Priority threshold" in the Self-driving settings.

**Checked, no change**

- Spend limit: $2,000, above the expected $1,080 a month after these changes.
- Daily report limit: 30 to 45 reports a day, no spikes.
- LLM evaluation reports: $12 a month across 6 evaluations, none over $3.
- Anomaly alerts: 19% of settled reports were resolved, above the project average.

¹ Share of settled reports that were resolved. A report is settled when it was first shown at least 14 days ago. A report is resolved when someone resolved it or its pull request merged. Newer reports have not had time to resolve, so they are not counted. Per resolved is an estimate.
```

After the report, ask which recommendations to apply.
Apply only the ones the user confirms, one at a time.
