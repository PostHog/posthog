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

import SourceSetupIntro from "../_snippets/source-setup-intro.mdx"
import SyncModes from "../_snippets/sync-modes.mdx"
import TroubleshootingLink from "../_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../_snippets/alpha-release.mdx"

<AlphaRelease />

[E2B](https://e2b.dev) runs secure cloud sandboxes for executing AI-agent-generated code. Linking E2B as a source syncs your sandbox infrastructure inventory — running and paused sandboxes, templates, and snapshots — into the PostHog data warehouse, so you can join agent sandbox activity with your product analytics.

## Prerequisites

Before connecting, you need a team-scoped E2B API key (prefixed `e2b_`). You can create one self-serve in your [E2B dashboard](https://e2b.dev/dashboard).

## Adding a data source

<SourceSetupIntro />

Provide your E2B API key. The key is team-scoped and is sent in the `X-API-Key` header on every request. E2B uses a single global API host (`api.e2b.app`); there are no regional endpoints to configure.

## Sync modes

<SyncModes />

E2B's list endpoints are point-in-time inventories and do not expose a server-side timestamp filter, so every table syncs as a full refresh. Each run replaces the table with the current state, deduplicated on the table's primary key.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **Invalid or revoked API key**: reconnect with a fresh team-scoped key from your E2B dashboard. Sandbox syncs that hit a `401` or `403` stop rather than retrying, since a credential problem cannot be resolved by retrying.
- **Terminated sandboxes are missing**: the `sandboxes` table only lists running and paused sandboxes. E2B does not expose terminated sandboxes through the list API, so they never appear here.

<TroubleshootingLink />
