---
name: simulate-returning-user
description: >
  Send synthetic single-session multi-page traffic to a URL and confirm
  PostHog $pageview events fire across page views. Use when verifying that
  cookies persist correctly, that the same distinct_id is reused across
  navigations, or when debugging session-stitching issues.
---

# Simulate returning-user traffic

Drives a single browser context across N page views (cookies and localStorage
persist), navigating between pages and reporting which PostHog events fired.
This matches the behavior of a single visitor browsing multiple pages on the
same site.

## When to use

- Confirm that PostHog reuses the same `distinct_id` across page views in a
  session (no fresh anonymous IDs per page).
- Confirm `$pageview` fires on every page view, not just the first.
- Reproduce "session not stitching" or "events split across multiple users"
  reports.

## How to invoke

Call the `simulate_returning_user` MCP tool with:

- `url` (required) — the page to visit each iteration.
- `page_views` (default `3`) — number of page views in the session.
- `interval` (default `5.0`) — seconds between page views.
- `posthog_host` (default `https://us.i.posthog.com`).

To exercise multi-page navigation, call the tool once per URL — the cookies
won't carry across calls (each call is a separate Playwright context). For
true multi-page browsing within one session, edit the URL list passed to the
underlying CLI: `traffic-sim returning-user --url A --url B --url C`.

## Interpreting the result

The structured response shape matches `simulate_new_user`. Key signals:

- `verified: true` and `pageviews >= page_views` — the session works.
- Same `distinct_id` across all pageviews (visible in PostHog UI under the
  run_id query param) — session stitching works.
- Different `distinct_id` per visit — likely a cookie domain or
  storage-permissions issue. Inspect the raw `posthog_requests` for `$session_id`
  values to diagnose.
