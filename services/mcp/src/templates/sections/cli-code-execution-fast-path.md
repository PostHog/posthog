### Script execution (`run` / `apply`)

```text
run <typescript source>   # execute a single-call SDK script
apply <plan-id>           # apply a confirmed plan
```

This server runs single-call scripts only: `import { client } from '@posthog/sdk'` then `export default await client.<domain>.<method>(<literal args>)`. Anything else gets an error asking you to split the work; use `sql` for queries. Reads return the tool's formatted output. A mutating call applies nothing: it returns a plan and a single-use plan id (three words, 10-minute expiry). Show the plan to the user; only after their explicit confirmation run `apply <plan-id>`. On divergence or expiry, re-run for a fresh plan.
