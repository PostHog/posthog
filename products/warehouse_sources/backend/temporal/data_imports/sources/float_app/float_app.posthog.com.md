---
title: Linking Float as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: FloatApp
beta: true
---

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

[Float](https://www.float.com/) is a resource-management and team-scheduling platform for capacity
planning. This source syncs your people, accounts, clients, departments, projects, phases,
allocations, milestones, logged time, time off, and holidays into the PostHog data warehouse so you
can join scheduling and capacity data with your product and revenue data.

## Prerequisites

- A Float account.
- A Float **access token**, created by the account owner. The token has the same access as its
  account owner and is sent as a `Bearer` token on every request.

## Adding a data source

<SourceSetupIntro />

You'll need:

- **Access token** – create one in Float under **Team Settings → Integrations → API**. Treat it like
  a password; regenerating it revokes the old one.

## Sync modes

<SyncModes />

Every Float table is **full refresh** only — Float's public API exposes no server-side
modified-since filter on its core resources, so there is no reliable incremental cursor to sync
against. The Delete Log tables (`deleted_tasks`, `deleted_timeoffs`, `deleted_logged_time`) are
tombstone logs for reconciling deletions and are **not** selected by default.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **401 Unauthorized** – the access token is invalid or has been revoked. Create a new token in Float
  under Team Settings → Integrations → API and reconnect.
- **403 Forbidden** – the token's account owner does not have permission to the data you're syncing.
  Confirm the owner's access and reconnect.
- **429 Too Many Requests** – Float rate-limits API traffic (200 GET requests/minute). The sync backs
  off and retries automatically; no action is needed.

<TroubleshootingLink />

<!--
DRAFT — this user-facing doc belongs in the posthog.com repo at
contents/docs/cdp/sources/float-app.md (served at /docs/cdp/sources/float-app). No posthog.com
checkout was available when this was written, so it is committed alongside the source to travel with
the PR. Copy it to posthog.com (dropping this comment) and run
`python manage.py audit_source_docs --docs-dir <posthog.com>/contents/docs/cdp/sources`.
-->
