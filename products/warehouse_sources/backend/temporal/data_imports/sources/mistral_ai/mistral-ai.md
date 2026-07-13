---
title: Linking Mistral AI as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: MistralAI
beta: true
---

<!--
This user-facing source doc belongs in the posthog.com repo at
contents/docs/cdp/sources/mistral-ai.md (served at /docs/cdp/sources/mistral-ai and
/docs/data-warehouse/sources/mistral-ai). It lives beside the source code only because this PR has no
posthog.com checkout to drop it into — copy it over and delete this note.
-->

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

Sync your [Mistral AI](https://mistral.ai) platform data into PostHog: available and fine-tuned models,
uploaded files, fine-tuning jobs, and batch inference jobs (plus beta agents, conversations, and
libraries). Use it to analyze fine-tuning progress, batch job throughput, and asset history alongside the
rest of your product data.

## Prerequisites

To connect Mistral AI, you need an account on [La Plateforme](https://console.mistral.ai) with an API
key. Free-tier keys work, but Mistral applies tighter workspace rate limits to them.

## Adding a data source

<SourceSetupIntro />

Provide your Mistral AI **API key**. You can create one in the
[API Keys](https://console.mistral.ai/api-keys) section of La Plateforme. Mistral keys are long-lived and
sent as a bearer token; the same key authenticates every table this connector syncs.

## Sync modes

<SyncModes />

Fine-tuning jobs and batch jobs support incremental syncing via their server-side `created_after` filter.
Models, files, and the beta agents, conversations, and libraries tables have no creation-time filter in
the API, so they sync as a full refresh each run. Those datasets are small, so full refresh is cheap.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

If the connection fails with an authorization error, confirm the API key is still active in La Plateforme
and has not been revoked. The beta tables (agents, conversations, libraries) are off by default because
Mistral marks those endpoint groups as beta and may change their shape; enable them only if you need them.

<TroubleshootingLink />
