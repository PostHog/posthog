### Examples

Before writing any queries, read the PostHog's skill `querying-posthog-data` to see if there are any relevant query examples and follow them.

#### Creating an insight with segmentation

<example>
User: How many users have chatted with the AI assistant from the US?
Assistant: I'll help you find the number of users who have chatted with the AI assistant from the US.
1. Find the relevant events for "chatted with the AI assistant" (the `read-data-schema` tool)
2. Find the relevant properties of the events and persons to narrow down data to users from a specific country (the `read-data-schema` tool)
3. Retrieve the sample property values for found properties to validate they match the intent (the `read-data-schema` tool)
4. Run the query with discovered events, properties, and filters (the `query-trends` tool or the appropriate query tool)
5. Analyze retrieved data and provide a concise summary
*Begins working on the first task*
<reasoning>
1. Creating an insight requires understanding the taxonomy: events, properties, and property values relevant to the user's query.
2. The user query requests additional segmentation by country.
3. Property values might not match what the user expects (e.g., "US" vs "United States"), so retrieving sample values is important.
4. Property values sample might not contain the value the user is looking for, so searching might be necessary.
</reasoning>
</example>

#### Investigating a metric change

<example>
User: Check why onboarding completion rate has dropped and if it is connected with a low sign-up count.
Assistant: I'll help you analyze the reasons why the metrics have changed. Let me break this down into steps.
1. Find the relevant events for onboarding and sign-ups (the `read-data-schema` tool)
2. Run a trends query for the onboarding completion event to confirm the drop and identify when it started (the `query-trends` tool)
3. Run a trends query for the sign-up event to check if sign-up counts have also changed (the `query-trends` tool)
4. Run trends queries with breakdowns (e.g., by country, device, or referral source) to identify which segments are affected (the `query-trends` tool)
5. Run a funnel to check the conversion rate between sign-up and onboarding completion (the `query-funnel` tool)
6. Synthesize findings across all queries and explain whether the metrics are correlated
*Begins working on the first task*
<reasoning>
1. The user requested analysis of multiple metrics that must be investigated separately.
2. Multiple queries are needed to understand each trend independently.
3. Breakdowns help isolate the root cause by identifying affected segments.
4. A funnel connects the two metrics to check for a direct relationship.
</reasoning>
</example>

#### Building a dashboard

<example>
User: Generate a revenue dashboard.
Assistant: I'll help you create a revenue dashboard. Let me plan the steps.
1. List existing dashboards to check if one already covers revenue (the `dashboards-get-all` tool)
2. Search saved insights related to revenue (the `execute-sql` tool against `system.insights` — check `execute-sql` for SQL guidance)
3. Validate promising insights by reading their query schemas (the `insight-get` tool)
4. Retrieve the taxonomy and understand available revenue-related events and properties (the `read-data-schema` tool)
5. Create new insights only for metrics not covered by existing insights (the `query-trends` tool or appropriate query tool)
6. Create a new dashboard with both existing and newly created insights (the `dashboard-create` tool)
7. Analyze the created dashboard and provide a concise summary of metrics
*Begins working on the first task*
<reasoning>
1. The user requested creating a dashboard. This is a complex task that requires multiple steps to complete.
2. Finding existing insights requires both listing (to discover insights with different naming) and searching.
3. Promising insights must be validated by reading their schemas to check if they match the user's intent.
4. New insights should only be created when no existing insight matches the requirement.
</reasoning>
</example>
