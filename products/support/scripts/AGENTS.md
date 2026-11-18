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
from lib.console import close_log_file, confirm, format_status_counts, log, printable, resolve_output_base, set_log_file
from lib.posthog_api import build_session, request_with_retries, resolve_host
```

- `lib.errors` - `PostHogScriptError`.
- `lib.console` - `log` (stderr output), `printable` (escape untrusted text), `confirm` (typed-keyword prompt, EOF-safe), `format_status_counts` (status histogram), `resolve_output_base` (numbers `--output` around an existing findings/log pair instead of overwriting it), `set_log_file`/`close_log_file` (stream every `log()` line to a file too, in addition to stderr - see Output below).
- `lib.posthog_api` - `resolve_host`, `request_with_retries` (every HTTP call), `build_session` (auth per the standard `--personal-api-key`/`--session-id` flags), `setup_session_auth` (the browser-session half of `build_session`, for a script that needs bespoke auth flow), `log_session_expiry` (logs the impersonated session's remaining idle-timeout time; no-op for personal-API-key auth), plus `MAX_RETRIES`.

Never re-implement retries, host resolution, auth, output, or the error type inside a script.
If a second script needs a new shared helper, add it to `lib/` (`errors` / `console` / `posthog_api`) instead of copying it.

## Networking

Route every request through `request_with_retries(session, method, url, ...)`.
It already retries 429 (with defensive Retry-After parsing) and 5xx with backoff.
Do not call `session.request` or `requests.get` directly.

Paginate defensively: honor the `next` URL for list APIs, and use keyset pagination (not `OFFSET`) for query-API scans, the way `find_affected_persons_hogql` does.

## Auth

Support both credentials, like the reference scripts:

- `--personal-api-key` / `POSTHOG_PERSONAL_API_KEY` (sent as a Bearer token).
- `--session-id` / `POSTHOG_SESSION_ID`, the browser `sessionid` cookie, for impersonated staff sessions.

Build the session with `build_session(args)` - it branches on `args.personal_api_key` vs. `args.session_id` and, for the browser-session path, calls `setup_session_auth` (CSRF token, HTTPS-only host-scoped cookie, mandatory acting-user confirmation).
Just call it; don't set the cookie or the `Authorization` header yourself.

## Output

All human output goes to **stderr** via `log()`, so **stdout** stays clean for `--output` JSON or piped data.
Do not use `print` (ruff `T2` flags it).

`--output NAME` (a base name, no extension) writes two files: `NAME-findings.json` (the scan report, written once discovery finishes) and `NAME-log.txt` (every `log()` line, streamed as it happens via `set_log_file`/`close_log_file`).
Resolve `args.output` through `resolve_output_base(args.output)` first, at the very top of `main()` - if either file already exists (a previous run at the same name), it numbers up (`NAME-2`, `NAME-3`, ...) instead of overwriting them, and reassigns `args.output` so every downstream use picks up the resolved name automatically.
Call `set_log_file(f"{args.output}-log.txt")` right after that (using the resolved name) and `close_log_file()` in a `finally` around the call into `run()`, so a crash or Ctrl-C mid-run still leaves a complete transcript up to that point - never buffer log lines in memory to write out at the end.

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
3. Offer `--output <name>` to dump the full affected set as JSON to `<name>-findings.json` (see Output above).
4. `--dry-run` returns here, changing nothing.
5. Otherwise confirm with `confirm(prompt, "<verb>", eof_message=...)` (a typed keyword such as `scrub` / `prune`), skippable with `--yes`.
6. When there is no bulk endpoint, mutate one item per request and report outcomes: count only 2xx as success, log a `FAILED: ...` line with the HTTP status/message immediately for every failure (don't wait until the run finishes), and log a running `format_status_counts` histogram every batch. Surface a 403 hint (read-only credential or field-level access control) and a final failure total at the end - don't re-print the individual failures there, they already scrolled by live.

Call out anything eventually-consistent (e.g. ingestion lag) in the module docstring so the operator isn't surprised when a value lingers after the run.

## Structure and style

- Module docstring first: what the script does, how it discovers targets, how it mutates them, any consistency caveats, and a usage block with the env vars and a `--dry-run` example.
- `parse_args() -> argparse.Namespace`, then `main() -> int` returning an exit code.
- If the script offers a `--output` findings report (the scrub/prune shape), keep `main()` thin and put the actual work in `run(args: argparse.Namespace) -> int`, so `main()` only wires up the log file around it:

  ```python
  def main() -> int:
      args = parse_args()
      if args.output:
          args.output = resolve_output_base(args.output)
          set_log_file(f"{args.output}-log.txt")
      try:
          return run(args)
      finally:
          close_log_file()


  def run(args: argparse.Namespace) -> int:
      ...
  ```

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
