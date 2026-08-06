---
title: Linking Concord as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Concord
beta: true
---

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

[Concord](https://www.concord.app/) is a contract lifecycle management (CLM) platform for
e-signatures, contract storage, negotiation, and approvals. This source syncs your agreements,
folders, clauses, tags, reports, organization members, and audit events into the PostHog data
warehouse so you can join contract data with your product and revenue data.

## Prerequisites

- A Concord account on a paid plan (API key generation is only available on paid plans).
- A Concord API key, generated from your account settings. It is sent as an `X-API-KEY` header.
- For the **events** (audit log) table, the API key must belong to a user with the **Administrator**
  role.

## Adding a data source

<SourceSetupIntro />

You'll need:

- **API key** – generate one in your Concord account settings. Concord sends it as the `X-API-KEY`
  header on every request.
- **Environment** – choose **Production** (`api.concordnow.com`) or **Sandbox**
  (`uat.concordnow.com`). The API key is environment-specific, so make sure it matches.
- **Organization ID** (optional) – leave blank to use the first organization your API key can
  access. Set it explicitly if your key has access to multiple organizations and you want a specific
  one.

## Sync modes

<SyncModes />

Agreements expose Concord's server-side `modifiedAt`/`createdAt` timestamp filters, so they support
**incremental** syncs. The audit **events** log is immutable and supports **append**-only syncing.
Every other table is **full refresh** only, since Concord does not expose a server-side change
filter for them.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **401 Unauthorized** – the API key is invalid, revoked, or for the wrong environment. Generate a
  new key in Concord and confirm the Production/Sandbox selection matches.
- **403 Forbidden on the events table** – the audit log requires the Administrator role. Either use
  a key for an admin user or deselect the **events** table.
- **No organizations accessible** – the API key can't see any organization. Confirm the key is valid
  and, if you set an Organization ID, that the key has access to it.

<TroubleshootingLink />

<!--
DRAFT — this user-facing doc belongs in the posthog.com repo at
contents/docs/cdp/sources/concord.md (served at /docs/cdp/sources/concord). No posthog.com checkout
was available when this was written, so it is committed alongside the source to travel with the PR.
Copy it to posthog.com (dropping this comment) and run
`python manage.py audit_source_docs --docs-dir <posthog.com>/contents/docs/cdp/sources`.
-->
