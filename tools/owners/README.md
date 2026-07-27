# posthog-owners

Resolver, linter, and formatter for PostHog's distributed `owners.yaml` ownership model.
It walks the `owners.yaml` / `product.yaml` files a repo carries, merges them nearest-file-wins, and answers "who owns this path" as a library or CLI, plus a lint that catches schema errors, dead globs, conflicts, and coverage gaps.
The ownership format and resolution semantics are documented in [`docs/internal/ownership-model-proposal.md`](../../docs/internal/ownership-model-proposal.md) and the `establishing-code-ownership` skill.

## Use it from another repo

The package is self-contained (stdlib + pyyaml + click), so any repo carrying `owners.yaml` files can run it without vendoring anything:

```bash
uvx --from "git+https://github.com/PostHog/posthog#subdirectory=tools/owners" owners lint
```

Pin to a commit for CI so the resolver semantics can't shift under you: append `@<sha>` to the URL (`...posthog@<sha>#subdirectory=tools/owners`).
