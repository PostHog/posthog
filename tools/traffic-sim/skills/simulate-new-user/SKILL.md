---
name: simulate-new-user
description: >
  Send synthetic first-time-visitor traffic to a URL and confirm that PostHog
  $pageview events fire. Use when a customer wants to verify that anonymous
  visitor tracking works, after deploying instrumentation changes, or when
  debugging "events not arriving" reports.
---

# Simulate new-user traffic

Drives a fresh browser context for each visit (no cookies, no localStorage),
goes to the given URL, scrolls a bit, and reports which PostHog events fired.
Each visit looks to PostHog like a brand-new anonymous visitor.

## When to use

- Confirm `$pageview` fires on the first visit (no cookies present).
- Confirm an anonymous `distinct_id` is generated and a PostHog request
  is sent within a few seconds of page load.
- Reproduce "events not showing up for new users" reports.

## How to invoke

Call the `simulate_new_user` MCP tool with:

- `url` (required) — the page to visit, e.g. `https://example.com/pricing`.
- `visits` (default `3`) — number of fresh-context visits.
- `interval` (default `5.0`) — seconds between visits.
- `posthog_host` (default `https://us.i.posthog.com`) — set to
  `https://eu.i.posthog.com` for the EU cloud, or your self-hosted host
  (e.g. `https://ph.example.com`).

Each visit takes ~10s of Playwright time plus the interval, so plan accordingly.

## Interpreting the result

The tool returns a structured summary:

```jsonc
{
  "run_id": "a1b2c3d4",
  "scenario": "new-user",
  "total_visits": 3,
  "posthog_requests": 6,
  "posthog_requests_ok": 6,
  "events_by_type": { "$pageview": 3, "$autocapture": 3 },
  "pageviews": 3,
  "errors": [],
  "verified": true,
}
```

- `verified: true` means at least one `$pageview` was captured per visit and
  no errors occurred — the new-user flow works.
- `verified: false` with `pageviews: 0` means PostHog isn't firing pageviews.
  Run `check_posthog_loading` next to see whether the snippet is even loaded.
- `posthog_requests_ok < posthog_requests` means PostHog returned non-2xx
  responses. Check the project's ingestion limits and api_host configuration.
