<!--
This is the user-facing posthog.com documentation for the E2B source. It lives here because no
posthog.com checkout was available when the source was implemented. Before release, move it to
`posthog.com/contents/docs/cdp/sources/e2b.md` (served at /docs/cdp/sources/e2b) and run
`python manage.py audit_source_docs --docs-dir <posthog.com>/contents/docs/cdp/sources`.
-->

---

title: Linking E2B as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: E2B
beta: true

---

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

[E2B](https://e2b.dev) runs secure cloud sandboxes for executing AI-agent-generated code. Linking E2B as a source syncs your sandbox infrastructure into the PostHog data warehouse: running and paused sandboxes, templates and their build history, snapshots, and CPU, memory and disk usage per sandbox. You can then join agent sandbox activity with your product analytics.

## Prerequisites

Before connecting, you need a team-scoped E2B API key (prefixed `e2b_`). You can create one self-serve in your [E2B dashboard](https://e2b.dev/dashboard).

## Adding a data source

<SourceSetupIntro />

Provide your E2B API key. The key is team-scoped and is sent in the `X-API-Key` header on every request. E2B uses a single global API host (`api.e2b.app`); there are no regional endpoints to configure.

The team ID is optional and only used by the `team_metrics` table, because E2B takes the team in the request path even when the API key already identifies it. You can copy the team ID from the URL of your E2B dashboard. Leave it blank if you do not want team metrics.

## Sync modes

<SyncModes />

E2B's list endpoints are point-in-time inventories and do not expose a server-side timestamp filter we can safely page against, so every table syncs as a full refresh. Each run replaces the table with the current state, deduplicated on the table's primary key.

`sandbox_metrics` asks E2B for the usage series of every sandbox, one request per sandbox, so it starts unselected. If you only need current usage, sync `sandbox_metrics_latest` instead. It reads up to 100 sandboxes per request.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **Invalid or revoked API key**: reconnect with a fresh team-scoped key from your E2B dashboard. Sandbox syncs that hit a `401` or `403` stop rather than retrying, since a credential problem cannot be resolved by retrying.
- **Terminated sandboxes are missing**: the `sandboxes` table only lists running and paused sandboxes. E2B does not expose terminated sandboxes through the list API, so they never appear here. The same applies to the metrics tables, which are built from that list.
- **Team metrics will not sync**: add your team ID to the source settings. E2B needs it in the request path, and no endpoint an API key can call returns it.

<TroubleshootingLink />
