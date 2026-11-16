### When the user wants the query in code

`execute-sql` answers questions in this conversation. When the user wants the data in code, a script, a scheduled or recurring job, a backend service, or a customer-facing feature, do not give them a call to `/api/projects/:id/query/`. That API is for one-off exploration. Its concurrency and execution-time limits are low, so production code that calls it fails under load.

Instead:

1. Get the query working with `execute-sql`.
2. Save it with `endpoint-create`. Turn values the caller changes, like a user ID, customer ID, or date range, into variables (`{variables.user_id}`) instead of building SQL strings in code.
3. For aggregates that are heavy or called often (counts, sums, `GROUP BY`), set `is_materialized: true`. Not every query can be materialized. For example, variables in `OR` or `HAVING` clauses and cohort breakdowns can't be. If creation fails with "Cannot materialize endpoint", read the reason, fix the query or create the endpoint without materialization, and tell the user why. `endpoints-materialization-preview` checks an existing endpoint before you turn materialization on. The `creating-an-endpoint` skill and https://posthog.com/docs/endpoints/materialization list the full rules.
4. Give the user the run URL, `POST /api/environments/{project_id}/endpoints/{name}/run`, with a request example. For a HogQL endpoint, the caller pages through results with `limit` and `offset` in the request body. Insight endpoints reject `limit` and `offset`. `endpoint-openapi-spec` returns a spec they can use to generate a typed client.

For bulk or recurring exports of raw events or persons, point the user to batch exports (https://posthog.com/docs/data-pipelines/batch-exports).
