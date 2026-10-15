---
title: Linking env0 as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Env0
beta: true
---

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

The env0 connector syncs your infrastructure-as-code data into PostHog: organizations, projects, teams, templates, organization members, environments, deployment history, the resources behind each deployment, drift causes, and cloud cost at the environment, project, and organization level. You can attribute cloud spend to teams and projects and analyze deployment and drift activity alongside your product data.

## Prerequisites

You need an env0 API key. Organization administrators can create an organization API key, or you can use a personal API key scoped to your user. The key needs read access to the organizations you want to sync.

Cost data additionally requires [cost monitoring](https://docs.envzero.com/docs/cost-monitoring) to be configured in env0 for the environments you want cost records for. Project and organization cost roll up the environments below them, so they are empty until cost monitoring is on.

## Adding a data source

<SourceSetupIntro />

To connect env0, you need an API key ID and an API key secret:

1. In env0, go to **Organization Settings** → **API Keys** (or create a [personal API key](https://docs.envzero.com/docs/api-keys) from your user settings).
2. Create a new API key and copy both the **API Key ID** and the **API Key Secret** — the secret is only shown once.
3. Paste them into the PostHog source setup form.

## Sync modes

<SyncModes />

The `deployments` table supports incremental sync on `startedAt`. Deployments can change after they first sync (their status and finish time land when the run completes), so incremental syncs re-pull a one-day window behind the last synced deployment to keep recently-synced rows fresh.

The `deployment_resources` table supports incremental sync on `deployment_started_at`, the start time of the deployment that managed the resource. An incremental sync only visits deployments inside that window, which keeps the table cheap to refresh. A full refresh visits every deployment in every environment, so use incremental sync once the first load finishes.

The cost tables always sync the last year of daily cost records, so full refresh is the right mode for them. The same goes for `drift_causes` and `organization_users`, which env0 returns in full on every request.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

**Missing cost data:** the cost tables only have rows for environments and projects where env0 cost monitoring is configured. Those without it are skipped.

**Rate limits:** env0 limits API usage to 1,000 requests per 60 seconds. Deployments and costs are fetched per environment, and `deployment_resources` is fetched per deployment, so accounts with very many environments or deployments may sync these tables slowly. The connector backs off and retries automatically.

**API keys in `organization_users`:** env0 counts organization API keys as users, so they appear in this table alongside people. The `app_metadata` column marks them. They are included because a deployment can be started by an API key, so leaving them out would make the table an incomplete lookup.

<TroubleshootingLink />
