<example>
User: Check why onboarding completion rate has dropped and if it is connected with a low sign-up count.
Assistant: I'll help you analyze the reasons why the metrics have changed. Let me break this down into steps.
1. Check the governed catalog for an onboarding conversion metric (the `metric-list` tool); run it with `data-catalog-metric-run` if one fits, with a warning if it is proposed or drifted, otherwise continue
2. Find the relevant events for onboarding and sign-ups (the `read-data-schema` tool)
3. Run a trends query for the onboarding completion event to confirm the drop and identify when it started (the `query-trends` tool)
4. Run a trends query for the sign-up event to check if sign-up counts have also changed (the `query-trends` tool)
5. Run trends queries with breakdowns (e.g., by country, device, or referral source) to identify which segments are affected (the `query-trends` tool)
6. Run a funnel to check the conversion rate between sign-up and onboarding completion (the `query-funnel` tool)
7. Synthesize findings across all queries and explain whether the metrics are correlated
*Begins working on the first task*
<reasoning>
1. A conversion rate is a governed shape, so the catalog is checked before any query.
2. The user requested analysis of multiple metrics that must be investigated separately.
2. Multiple queries are needed to understand each trend independently.
3. Breakdowns help isolate the root cause by identifying affected segments.
4. A funnel connects the two metrics to check for a direct relationship.
</reasoning>
</example>
