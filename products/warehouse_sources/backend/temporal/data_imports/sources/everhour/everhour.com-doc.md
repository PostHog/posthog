<!--
This is the user-facing posthog.com documentation for the Everhour source.

There is no posthog.com checkout in this environment, so it cannot be placed at its final
location here. Copy this file (without this comment block) to:

    posthog.com/contents/docs/cdp/sources/everhour.md

Then run, from the posthog repo:

    python manage.py audit_source_docs --docs-dir ../posthog.com/contents/docs/cdp/sources
-->

---

title: Linking Everhour as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Everhour
beta: true

---

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

[Everhour](https://everhour.com) is a time-tracking, budgeting, and resource-planning tool for teams. This source syncs your Everhour clients, projects, tasks, team members, and time records into the PostHog data warehouse so you can join time-tracking data with your product and revenue data.

## Prerequisites

Using the Everhour API requires a **paid Everhour plan**. You'll need your personal API key, which you can find in your [Everhour profile settings](https://app.everhour.com/#/account/profile) under the API section.

## Adding a data source

<SourceSetupIntro />

You'll need your Everhour **API key**:

1. Sign in to [Everhour](https://app.everhour.com).
2. Open your [profile settings](https://app.everhour.com/#/account/profile).
3. Copy the key from the **API** section.

Paste the key into the API key field when connecting the source in PostHog. The key is sent only over the `X-Api-Key` header to `https://api.everhour.com`.

## Sync modes

<SyncModes />

Most Everhour reference tables (clients, projects, users, tasks) have no server-side change timestamp, so they sync as **full refresh**. **Time records** support incremental sync: PostHog uses Everhour's server-side `from`/`to` date window to pull only entries on or after the last synced date.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

A few notes:

- **Time values are in seconds.** The `time` field on time records and tasks is a duration in seconds (e.g. `3600` is one hour).
- **Tasks are fanned out per project.** Each task row carries the parent `project_id` it was fetched under, and the primary key is `(project_id, id)` because a task can belong to more than one project.
- **Integration IDs are prefixed.** Projects and tasks imported from integrations use a prefixed id (e.g. `as:` for Asana, `jira:` for Jira, `tr:` for Trello).

## Troubleshooting

- **Invalid API key** — if the connection fails to validate, regenerate your key in your Everhour profile settings and reconnect. The key requires a paid Everhour plan.
- **Rate limits** — Everhour rate-limits at roughly 20 requests per 10 seconds per API key. PostHog automatically honors the `Retry-After` header and backs off, so large initial syncs of time records may take a while to complete.

<TroubleshootingLink />
