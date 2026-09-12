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

### From a consumer that is not Python

`python -m posthog_owners` answers the same question as JSON, with no click and no project sync. Stdlib plus pyyaml is enough.
It reads repo-relative paths from stdin or argv and writes a single JSON object keyed by path:

```bash
echo "posthog/models/team.py" | PYTHONPATH=/fetched/tools/owners python3 -m posthog_owners --repo-root /fetched
```

`PYTHONPATH` names the directory holding the `posthog_owners` package. `--repo-root` names the tree holding the ownership files; the example fetched both into one scratch directory, but they are independent.
Any Python 3.10+ interpreter with pyyaml works, so `uv run --no-project --with pyyaml python` is enough if you would rather not install it.

```json
{
  "posthog/models/team.py": {
    "owners": ["team-x"],
    "status": "active",
    "slack": "#team-x",
    "source": "posthog/owners.yaml"
  }
}
```

Without `--repo-root` the resolver locates the repo with `git rev-parse`, so it needs a real worktree.
Pass the flag when the ownership files sit in a directory that is not one: a sparse fetch, an export, or a scratch copy of just the `owners.yaml` / `product.yaml` files.
Add `--purpose notifications` to resolve `slack` to each team's automation channel instead of its people channel.
