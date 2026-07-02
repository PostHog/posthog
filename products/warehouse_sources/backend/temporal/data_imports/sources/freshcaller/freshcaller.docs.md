<!--
This is the user-facing source doc. It belongs in the posthog.com repo at
contents/docs/cdp/sources/freshcaller.md (served at /docs/cdp/sources/freshcaller and
/docs/data-warehouse/sources/freshcaller). It lives here in the PR because no posthog.com
checkout was available; move it into posthog.com and delete this file before/after merge.
-->
---
title: Linking Freshcaller as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Freshcaller
---

import SourceSetupIntro from "../_snippets/source-setup-intro.mdx"
import SyncModes from "../_snippets/sync-modes.mdx"
import TroubleshootingLink from "../_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../_snippets/alpha-release.mdx"

<AlphaRelease />

Freshcaller is Freshworks' cloud-based call center and phone system.
This connector syncs your Freshcaller users, teams, calls, and per-call metrics into the PostHog data warehouse,
so you can join call-center activity with product analytics — for example, correlating support call volume with feature usage or churn.

## Prerequisites

- A Freshcaller account.
- The API key of an agent or admin whose role grants read access to the data you want to sync.
  Call, user, and team data is only as complete as that agent's permissions allow.

## Adding a data source

<SourceSetupIntro />

You'll need two things:

- **Account name** — the subdomain in your Freshcaller URL. For `acme.freshcaller.com`, the account name is `acme`.
- **API key** — open your Freshcaller **Profile settings** (click your profile picture in the top-right → **Profile settings**).
  Your API key is shown in the right sidebar.

Freshcaller authenticates the data API with this API key sent in the `X-Api-Auth` header.
OAuth in Freshcaller is only for building marketplace apps, not for the data API — use the API key.

## Sync modes

<SyncModes />

Calls and Call Metrics support incremental sync on their `created_time` field (Freshcaller filters these server-side by a time window).
Users and Teams have no server-side time filter, so they sync as a full refresh each run.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **Authentication failed (401):** double-check the account name (the subdomain, not the full URL) and that the API key was copied in full from **Profile settings**.
- **Permission errors (403) on a specific table:** the agent whose API key you used doesn't have read access to that resource. Use an admin key or grant the role the required scope, then re-sync.
- **Rate limiting:** Freshcaller enforces per-minute rate limits that vary by plan tier. The connector automatically backs off and retries, so transient throttling resolves on its own.

<TroubleshootingLink />
