Pass one command per call in the `command` parameter. Supported commands:

```text
types <query | TypeName... | domain.method | domain>  # SDK discovery: exact names fetch full declarations, anything else searches
run <typescript source>                                # execute a script. Read-only → output; mutating → plan to confirm
apply <plan-id>                                        # apply a confirmed plan (single-use three-word id, 10 minute expiry)
sql <hogql>                                            # run a HogQL query directly (rest of the command, may span lines)
```

**Script contract (`run`):**

- `import { client } from '@posthog/sdk'` — the only import that resolves; `require()` is not available.
- Top-level `await` is fine. The script must `export default` the value to return; keep it a small summary, not raw API dumps.
- Scripts are typechecked before execution — diagnostics come back with line numbers; fix and re-run.
- Discover exact method signatures with `types` (or the cheat sheet below) first — do not guess them.

**`script` parameter:** for any multi-line script, pass the TypeScript in the separate `script` parameter with `{ "command": "run" }` — it needs no JSON-string escaping inside `command`.

**Fast path:** a script that is a single SDK call with literal arguments runs without a sandbox — reads return the matching tool's formatted output directly, at the same latency as a plain tool call, and a mutating call still returns a plan first. Scripts with variables, loops, or multiple calls run sandboxed and see full API objects instead. Write the natural script for the task; the server picks the execution strategy.
