---
title: Linking Firecrawl as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Firecrawl
beta: true
---

import SourceSetupIntro from "../_snippets/source-setup-intro.mdx"
import SyncModes from "../_snippets/sync-modes.mdx"
import TroubleshootingLink from "../_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../_snippets/alpha-release.mdx"

<AlphaRelease />

[Firecrawl](https://www.firecrawl.dev) is a web scraping and crawling API. This connector syncs your Firecrawl account's operational data - job activity, credit and token usage, active crawls, and change-detection monitors - into the PostHog Data warehouse, so you can track your scraping usage and spend alongside the rest of your data.

## Prerequisites

- A Firecrawl account.
- A Firecrawl API key, which you can create in your [Firecrawl dashboard](https://www.firecrawl.dev/app/api-keys). A single key grants access to every table this connector syncs.

## Adding a data source

<SourceSetupIntro />

Provide your Firecrawl **API key** (it starts with `fc-`). That's the only credential the connector needs.

## Sync modes

<SyncModes />

Firecrawl's account endpoints don't expose a server-side "updated since" filter, so every Firecrawl table syncs with **full refresh** - each sync replaces the table with the current data from the API.

One table is worth calling out: `team_activity` is a rolling log that Firecrawl only retains for the **last 24 hours**. Older activity can't be backfilled, so schedule frequent syncs if you want to accumulate a longer history of jobs in the warehouse.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

The `monitor_checks` table is disabled by default because it fans out one request per monitor - enable it in the table picker if you use Firecrawl monitors and want their individual check runs.

## Troubleshooting

- **Invalid API key:** if the connection fails to validate, confirm the key is active in your [Firecrawl dashboard](https://www.firecrawl.dev/app/api-keys) and that you pasted the full `fc-...` value.
- **Empty `team_activity`:** the endpoint only returns the last 24 hours of jobs. If your account hasn't run any jobs in that window, the table will be empty until it does.
- **Rate limits:** Firecrawl enforces plan-based rate and concurrency limits. The connector automatically backs off and retries when it's throttled.

<TroubleshootingLink />
