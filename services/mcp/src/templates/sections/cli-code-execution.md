### Script execution (`run` / `apply`)

```text
run <typescript source>   # compile-check, then execute
apply <plan-id>           # apply a confirmed plan
```

Script contract: `import { client } from '@posthog/sdk'` (the only import), top-level `await` is fine, `export default` the result. Get signatures from `types` first — never guess. A single SDK call with literal args skips the sandbox and returns the tool's formatted output; other scripts see full API objects.

A mutating script applies nothing: it returns a plan and a single-use plan id (three words, 10-minute expiry). Show the plan to the user; only after their explicit confirmation run `apply <plan-id>`. On divergence ("the world changed") or expiry, re-run the script for a fresh plan — never retry `apply` blindly.
