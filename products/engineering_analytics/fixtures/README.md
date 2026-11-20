# Engineering analytics fixtures

The two JSON files are a bounded snapshot of recent `PostHog/posthog` pull requests and workflow runs.
`fetch.py` trims each record to the fields the curated builders read.

## Refresh the snapshot

The script needs an authenticated `gh` CLI and makes about 160 API requests with the default caps.

```sh
python products/engineering_analytics/fixtures/fetch.py
```

## Load the snapshot into a local stack

Start the dev stack first, because the command needs ClickHouse and object storage.

```sh
python manage.py seed_engineering_analytics --team-id 1
```

The command creates a GitHub source for the team with these warehouse tables: pull requests, workflow runs, workflow jobs, team members, issue events, reviews, deployments and deployment statuses.
It also creates a Trunk source with quarantined tests, per-test CI spans in Traces, and thinned CI failure lines in Logs.

- The command rebases timestamps so the newest row lands at the current time, because the product's queries use the server's `now()`. Pass `--keep-dates` to keep the original timestamps.
- A second run replaces the seeded tables. The command never changes a table that a real connected source owns.
- The `engineering-analytics` feature flag gates the product. Create an active boolean flag with that key in your local project.
