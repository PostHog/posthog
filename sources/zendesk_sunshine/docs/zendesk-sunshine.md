---
title: Linking Zendesk Sunshine as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: ZendeskSunshine
beta: true
---

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

The Zendesk Sunshine source syncs your Zendesk custom objects into PostHog.

New sources use Zendesk's current custom objects API (`/api/v2/custom_objects`, version `v2`) and sync custom object definitions, their records, and field schemas.

> **Note:** Zendesk is removing the legacy Sunshine custom objects API (`/api/sunshine/`, version `v1`) on June 30, 2026, and no new legacy objects can be created since January 15, 2026. Sources created before `v2` became the default are still pinned to `v1` and keep working until then. PostHog shows a deprecation warning on those sources; move each one to `v2` from the source's settings before the sunset date. Because the `v1` and `v2` table sets differ, switching a source to `v2` resyncs it under the new tables rather than converting the existing ones in place.

## Prerequisites

- A Zendesk plan that includes custom objects, with custom objects activated by an admin in Admin Center (Objects and rules → Custom objects).
- API token access enabled for your Zendesk account (Admin Center → Apps and integrations → APIs → Zendesk API).
- A Zendesk API token. Generate one in Admin Center under Apps and integrations → APIs → Zendesk API → Add API token.

## Adding a data source

<SourceSetupIntro />

You'll need:

1. Your Zendesk subdomain (the `yourcompany` part of `yourcompany.zendesk.com`).
2. The email address of the Zendesk user the API token belongs to.
3. The API token.

## Sync modes

<SyncModes />

On `v2`, all tables sync as full refreshes; the current records API has no server-side `updated_at` filter, so records are fetched sorted by `updated_at`. On legacy `v1`, object records support incremental syncs on `updated_at` via the Sunshine search API, and the other tables are small catalogs that full refresh.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **"Zendesk rejected the credentials"**: check the subdomain, email address, and API token, and confirm token access is enabled for your account. The username Zendesk expects is `you@example.com/token`; PostHog builds this for you, so enter your plain email address.
- **"The Zendesk Sunshine (legacy custom objects) API is not available"**: legacy custom objects are not activated for the account, or the plan doesn't include them. An admin can activate them in Admin Center under Objects and rules → Custom objects.

<TroubleshootingLink />
