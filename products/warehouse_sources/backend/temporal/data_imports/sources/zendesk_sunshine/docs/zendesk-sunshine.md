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

The Zendesk Sunshine source syncs your legacy Zendesk custom objects (the Sunshine custom data API) into PostHog: object types, object records, relationship types, relationship records, permission policies, and account limits.

> **Note:** Zendesk is retiring legacy custom objects in 2026 and no new legacy objects can be created since January 15, 2026. This source reads the legacy `/api/sunshine/` API, so it is mainly useful for keeping a queryable copy of that data before Zendesk removes it. It does not cover the newer custom objects experience under the Zendesk Support API.

## Prerequisites

- A Zendesk plan that includes legacy custom objects, with legacy custom objects activated by an admin in Admin Center (Objects and rules → Custom objects).
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

Object records support incremental syncs on `updated_at`, served by Zendesk's custom object search API which filters server side. All other tables are small catalogs and sync as full refreshes.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **"Zendesk rejected the credentials"**: check the subdomain, email address, and API token, and confirm token access is enabled for your account. The username Zendesk expects is `you@example.com/token`; PostHog builds this for you, so enter your plain email address.
- **"The Zendesk Sunshine (legacy custom objects) API is not available"**: legacy custom objects are not activated for the account, or the plan doesn't include them. An admin can activate them in Admin Center under Objects and rules → Custom objects.

<TroubleshootingLink />
