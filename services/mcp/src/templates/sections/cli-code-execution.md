### Code execution (`types` / `run` / `apply`)

For multi-step workflows (read → filter → mutate many objects), write one TypeScript script against `@posthog/sdk` instead of many `call` round trips.

```text
types <query>                                    # search SDK methods (regex or substring); signatures are scope-annotated for this token
types show <symbol | domain.method | domain>     # full TS declarations plus related types, to a token budget
run <typescript source>                          # compile-check, then execute the script
apply <plan token>                               # apply a previously returned plan after the user confirms
```

Script contract: `import { client } from '@posthog/sdk'`, top-level `await` is fine, and the script must `export default` the value to return. Only `@posthog/sdk` can be imported. Discover the exact method signatures with `types` first — do not guess them.

Plan/apply contract: a read-only script returns its output immediately. A script that attempts mutations does NOT apply them — it returns a plan (the exact set of changes), a provisional output, and a single-use plan token (10 minute expiry). Show the plan to the user and only after their explicit confirmation run `apply <token>`. If the apply reports divergence ("the world changed") or the token expired, re-run the script to get a fresh plan — never retry `apply` blindly.
