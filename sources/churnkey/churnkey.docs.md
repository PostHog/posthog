---
title: Linking Churnkey as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Churnkey
---

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

[Churnkey](https://churnkey.co) is a churn-prevention and failed-payment-recovery platform for subscription businesses. This source syncs your Churnkey cancel-flow **sessions** into the PostHog Data warehouse, so you can analyze why customers cancel, which retention offers they accept, and how your cancel flow performs alongside the rest of your product data.

## Prerequisites

To connect Churnkey, you need:

- A Churnkey account with cancel flows installed.
- A **Data API key**. This is distinct from your Cancel Flow API key and must be requested from Churnkey support at [support@churnkey.co](mailto:support@churnkey.co).
- Your **App ID**, found in Churnkey under **Settings → Account** (the Data API key is shown there too).

## Adding a data source

<SourceSetupIntro />

Provide the following credentials:

- **Data API key**: the `data_…` key issued by Churnkey support.
- **App ID**: your Churnkey application ID from **Settings → Account**.

Both are sent to the Churnkey Data API (`https://api.churnkey.co/v1/data`) on every request — the key in the `x-ck-api-key` header and the App ID in the `x-ck-app` header.

## Sync modes

<SyncModes />

The Churnkey Data API does not expose a per-record update cursor for sessions, so this source syncs **full refresh** only. Each sync re-pulls the sessions and de-duplicates on the session ID.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **"Invalid Churnkey Data API key"** — confirm you are using the **Data API key** (request it from [support@churnkey.co](mailto:support@churnkey.co)), not your Cancel Flow API key.
- **"Churnkey App ID not recognized"** — copy the App ID exactly as shown under **Settings → Account**; an unknown App ID is rejected by the API.

<TroubleshootingLink />
