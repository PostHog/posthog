---
title: Linking env0 as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Env0
beta: true
---

import SourceSetupIntro from "../_snippets/source-setup-intro.mdx"
import SyncModes from "../_snippets/sync-modes.mdx"
import TroubleshootingLink from "../_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../_snippets/alpha-release.mdx"

<AlphaRelease />

The env0 connector syncs your infrastructure-as-code data — organizations, projects, environments, deployment history, teams, templates, and per-environment cloud cost — into PostHog, so you can attribute cloud spend to teams and projects and analyze deployment activity alongside your product data.

## Prerequisites

You need an env0 API key. Organization administrators can create an organization API key, or you can use a personal API key scoped to your user. The key needs read access to the organizations you want to sync.

Environment cost data additionally requires [cost monitoring](https://docs.envzero.com/docs/cost-monitoring) to be configured in env0 for the environments you want cost records for.

## Adding a data source

<SourceSetupIntro />

To connect env0, you need an API key ID and an API key secret:

1. In env0, go to **Organization Settings** → **API Keys** (or create a [personal API key](https://docs.envzero.com/docs/api-keys) from your user settings).
2. Create a new API key and copy both the **API Key ID** and the **API Key Secret** — the secret is only shown once.
3. Paste them into the PostHog source setup form.

## Sync modes

<SyncModes />

The `deployments` table supports incremental sync on `startedAt`. Deployments can change after they first sync (their status and finish time land when the run completes), so incremental syncs re-pull a one-day window behind the last synced deployment to keep recently-synced rows fresh.

The `environment_costs` table always syncs the last year of daily cost records per environment, so full refresh is the right mode for it.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

**Missing cost data:** the `environment_costs` table only has rows for environments where env0 cost monitoring is configured. Environments without it are skipped.

**Rate limits:** env0 limits API usage to 1,000 requests per 60 seconds. Deployments and costs are fetched per environment, so accounts with very many environments may sync these tables slowly — the connector backs off and retries automatically.

<TroubleshootingLink />
