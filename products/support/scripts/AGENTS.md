# Support scripts

One-off operational CLIs that support and staff run against a live PostHog project
(scrub person properties, prune property definitions, and so on).
They talk to the public REST and query APIs over the network and are never imported by the app.
Shared plumbing lives in `lib/`, so a new script is mostly its own discovery/mutation logic plus a thin `main()`.

`scrub_person_properties.py` and `prune_property_definitions.py` are the reference implementations.
A new script should read like a third sibling of those two. Copy their shape.

## Use the shared lib, don't re-roll it

Import each name straight from its defining module (`lib` resolves because a script's own directory is on `sys.path` when run directly).
Don't re-export through `lib/__init__.py` - a `from .` re-export there trips the `no-init-reexports` semgrep rule.

```python
from lib.errors import PostHogScriptError            # the one error type; raise for any expected, operator-facing failure
from lib.console import confirm, format_status_counts, log, printable
from lib.posthog_api import request_with_retries, resolve_host, setup_session_auth
```

- `lib.errors` - `PostHogScriptError`.
- `lib.console` - `log` (stderr output), `printable` (escape untrusted text), `confirm` (typed-keyword prompt, EOF-safe), `format_status_counts` (status histogram).
- `lib.posthog_api` - `resolve_host`, `request_with_retries` (every HTTP call), `setup_session_auth` (browser-session/impersonation auth), plus `MAX_RETRIES`.

Never re-implement retries, host resolution, auth, output, or the error type inside a script.
If a second script needs a new shared helper, add it to `lib/` (`errors` / `console` / `posthog_api`) instead of copying it.

## Networking

Route every request through `request_with_retries(session, method, url, ...)`.
It already retries 429 (with defensive Retry-After parsing) and 5xx with backoff.
Do not call `session.request` or `requests.get` directly.

Build one `requests.Session`.
For a personal API key set `session.headers["Authorization"] = f"Bearer {key}"`; for a browser session call `setup_session_auth(session, host, session_id)`.

Paginate defensively: honor the `next` URL for list APIs, and use keyset pagination (not `OFFSET`) for query-API scans, the way `find_affected_persons_hogql` does.

## Auth

Support both credentials, like the reference scripts:

- `--personal-api-key` / `POSTHOG_PERSONAL_API_KEY` (sent as a Bearer token).
- `--session-id` / `POSTHOG_SESSION_ID`, the browser `sessionid` cookie, for impersonated staff sessions.

`setup_session_auth` handles the CSRF token, the HTTPS-only host-scoped cookie, and the mandatory acting-user confirmation.
Just call it; don't set the cookie yourself.

## Output

All human output goes to **stderr** via `log()`, so **stdout** stays clean for `--output` JSON or piped data.
Do not use `print` (ruff `T2` flags it).

Wrap any value that originated from ingested data (property names, `distinct_id`s, an API error body) in `printable()` before logging it.
Those strings can carry terminal escape sequences that would otherwise spoof or wipe the operator's terminal.

## Arguments (argparse)

- Use `argparse.ArgumentDefaultsHelpFormatter`.
- Resolve env-backed args _after_ `parse_args()` so `--help` never prints a key read from the environment.
- Reuse the standard flags and their meanings: `--host` (through `resolve_host`; default `POSTHOG_HOST`, else US), `--project-id` (`POSTHOG_PROJECT_ID`, required), `--dry-run`, `--yes` / `-y`, `--output`, `--page-size`, `--batch-size`.
- Validate numeric args before any request runs: reject a non-positive `--page-size` / `--batch-size` with `parser.error(...)`. A zero step otherwise loops forever or crashes mid-run.

## Destructive-operation safety

Anything that writes or deletes follows this order:

1. Scan and dedupe the affected set.
2. Log a total, a per-target breakdown, and a sample (first ~10).
3. Offer `--output <file>` to dump the full affected set as JSON.
4. `--dry-run` returns here, changing nothing.
5. Otherwise confirm with `confirm(prompt, "<verb>", eof_message=...)` (a typed keyword such as `scrub` / `prune`), skippable with `--yes`.
6. When there is no bulk endpoint, mutate one item per request and report outcomes with `format_status_counts`: count only 2xx as success, surface a 403 hint (read-only credential or field-level access control), and cap the printed failure list.

Call out anything eventually-consistent (e.g. ingestion lag) in the module docstring so the operator isn't surprised when a value lingers after the run.

## Structure and style

- Module docstring first: what the script does, how it discovers targets, how it mutates them, any consistency caveats, and a usage block with the env vars and a `--dry-run` example.
- `parse_args() -> argparse.Namespace`, then `main() -> int` returning an exit code.
- Standard bottom guard:

  ```python
  if __name__ == "__main__":
      try:
          sys.exit(main())
      except PostHogScriptError as err:
          log(f"Error: {printable(str(err))}")
          sys.exit(1)
      except KeyboardInterrupt:
          log("\nInterrupted.")
          sys.exit(130)
  ```

- These files **are** type-checked and linted (this directory is not in the mypy or ruff script exclusions).
  Fully annotate every signature, keep imports at module level (no inline imports; `PLC0415` is enforced), and run `ruff check --fix && ruff format` on your changes.
