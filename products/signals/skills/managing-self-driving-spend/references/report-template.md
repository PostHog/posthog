# Report template

Keep the report proportional to the question. For a full review, show:

- **Scope:** canonical project, UTC period, and summary `as_of`.
- **Recorded usage:** finalized credits and USD using `pricing.usd_per_credit`; sources plus scout execution reconcile to the total. Show source processing, research, and implementation separately when useful.
- **Billing:** current billed spend and cap from `posthog:billing-limits-get`, separately from recorded usage. Identify exempt credits as a subset; non-exempt usage is not necessarily the invoice.
- **Completeness:** unsettled credits for work created in the period, untracked scout runs, incomplete accounting, and unattributed costs. Missing amounts are unknown, not zero.
- **Breakdowns:** source/scout, recorded USD, exempt USD, reports created, resolved share, and estimated cost per resolved report. For scouts add runs and runs with neither new nor edited reports. Deduplicate report IDs for project totals.
- **Daily trend:** finalized usage by day, highlighting the source, scout, or work kind behind spikes.
- **Recommendations:** rank specific changes by estimated monthly savings, state what the user loses, and name the tool or app setting. Include controls checked that need no change.

Resolution yield uses reports first shown at least 14 days ago, looking back 60 days. Write "too new" below 20 settled reports.
Cost per resolved report is an estimate: period spend divided by reports created times the settled resolution rate. Its spend and report cohorts differ.
Implementation costs are measured; savings from a proposed threshold or steering change still require an estimate.
Apply only changes the user explicitly confirms and read each setting back.
