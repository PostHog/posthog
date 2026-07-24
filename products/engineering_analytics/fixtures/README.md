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

Creates the `github_pull_requests`, `github_workflow_runs`, `github_workflow_jobs`, and `github_team_members` warehouse tables for the team (CSV-backed, same mechanism as the demo data generator), plus per-test CI spans in Traces (flaky tests, team CI health) and thinned CI failure lines in Logs (broken tests, per-run failure logs).

The sidebar entry is gated on the `engineering-analytics` feature flag, and local dev evaluates flags against your local project (`SELF_CAPTURE`) — create an active boolean flag with that key in your local project to see the product.
Timestamps are rebased so the newest row lands at "now" (the product's queries window on server-side `now()`); pass `--keep-dates` for the faithful snapshot.
Re-running replaces the previously seeded tables; tables owned by a real connected GitHub source are never touched.
