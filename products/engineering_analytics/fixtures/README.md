# Engineering analytics fixtures

A bounded, real snapshot of PostHog/posthog GitHub data (recent pull requests + workflow runs), trimmed to the fields the curated warehouse views read.
Used to get realistic data into a local stack without connecting a live GitHub warehouse source.

## Refresh the snapshot

Requires an authenticated `gh` CLI; roughly 160 API requests with the default caps.

```sh
python products/engineering_analytics/fixtures/fetch.py
```

## Load into a local stack

With the dev stack running (ClickHouse + object storage):

```sh
python manage.py seed_engineering_analytics --team-id 1
```

Creates the `github_pull_requests` and `github_workflow_runs` warehouse tables for the team (CSV-backed, same mechanism as the demo data generator).

The sidebar entry is gated on the `engineering-analytics` feature flag, and local dev evaluates flags against your local project (`SELF_CAPTURE`) — create an active boolean flag with that key in your local project to see the product.
Timestamps are rebased so the newest row lands at "now" (the product's queries window on server-side `now()`); pass `--keep-dates` for the faithful snapshot.
Re-running replaces the previously seeded tables; tables owned by a real connected GitHub source are never touched.
