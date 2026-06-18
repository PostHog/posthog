---
name: check-posthog-loading
description: >
  Inspect how the PostHog JavaScript SDK is loaded across a list of URLs.
  Use to confirm consistent installation across pages, find pages missing
  the snippet, detect mismatched API keys or hosts between pages, and verify
  the load method (head snippet vs deferred vs array.js).
---

# Check PostHog loading

For each URL, navigates a real browser to the page, waits for PostHog to
initialize, and reports:

- Whether `window.posthog` is defined and `__loaded`.
- Which load method was used: `head_snippet`, `snippet`, `array_js_only`, or `none`.
- Where in the document the snippet lives (`head` / `body`).
- The init config: `api_key`, `api_host`, `person_profiles`.
- Runtime state including the assigned `distinct_id`.

## When to use

- Sanity-check a fresh install — does the snippet actually load on every page?
- After a page-template change — did one page lose the snippet?
- When investigating split data — are some pages pointing at a different
  `api_host` or `api_key` than others?
- Onboarding a new customer — confirm SDK is wired up before debugging events.

## How to invoke

Call the `check_posthog_loading` MCP tool with:

- `urls` (required) — list of URLs to inspect.
- `posthog_host` (default `https://us.i.posthog.com`).

Returns a structured summary with which URLs loaded successfully, which
didn't, and the load-method distribution.

## Interpreting the result

Look for these red flags:

- **Empty `loaded` list, full `not_loaded` list** — snippet not present
  anywhere. Re-run install or check that the layout includes the snippet.
- **Mixed `loaded` / `not_loaded`** — snippet missing from some pages.
  Common cause: a page rendered by a different template or layout.
- **Multiple distinct `api_key` values across pages** — a page is pointing
  at the wrong PostHog project.
- **Multiple distinct `api_host` values** — a page is pointing at the wrong
  ingestion endpoint (e.g. EU cloud vs US cloud, or vs a self-hosted reverse
  proxy). This causes events to land in different projects than expected.
- **`load_method: array_js_only`** with no init config — `array.js` was
  loaded but `posthog.init()` was never called. Common with manual installs
  that miss the second half.
