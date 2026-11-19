# Report template

Keep the report proportional to the question. For a full review, show:

- **Scope:** canonical project, UTC period, and summary `as_of`.
- **Recorded usage:** finalized AI credits and their USD value using `pricing.usd_per_credit`; sources plus scout execution reconcile to the total. Always show processing, research, scout execution, and implementation separately, including any that are zero.
- **Billing:** current billed spend and cap from `posthog:billing-limits-get`, separately from recorded usage. Identify exempt credits as a subset; non-exempt usage is not necessarily the invoice.
- **Not counted yet:** in plain words, say how many AI credits of work are still running (unsettled credits), how many scout runs have no cost record yet (untracked runs), and how much spend could not be tied to a source or scout (unattributed costs). Leave out any that are zero, and do not use field names. Missing amounts are unknown, not zero.
- **Breakdowns:** source/scout, recorded USD, exempt USD, reports created, resolved share, and estimated cost per resolved report, with the baselines they are compared to. For scouts add runs and runs with neither new nor edited reports. Deduplicate report IDs for project totals. On a large project, show the top 10 to 15 items and group the rest in one row with their total.
- **Daily trend:** finalized usage by day, highlighting the source, scout, or work kind behind spikes.
- **Recommendations:** rank specific changes by estimated monthly savings, state what the user loses, and name the tool or app setting. Name each change with a verb the user acts on, such as "Run less often", "Add a pre-check", or "Turn off". Include controls checked that need no change.

Resolution yield uses reports first shown at least 14 days ago, looking back 60 days. Write "too new" below 20 settled reports.
In the report, say "resolved" and never "settled". Explain it once: "Resolved: of reports first shown at least 14 days ago, the share that got resolved."
Cost per resolved report is an estimate: period spend divided by reports created times the settled resolution rate. Its spend and report cohorts differ. Below about 3 expected resolved reports, write "too few reports to estimate".
Automatic implementation costs are measured; savings from a proposed threshold or steering change still require an estimate.
When you report implementation spend, say that it excludes fixes a person starts from a report, which are metered as PostHog AI.
Apply only changes the user explicitly confirms and read each setting back.
