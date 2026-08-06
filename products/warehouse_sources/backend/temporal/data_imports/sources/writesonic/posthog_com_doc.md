---
title: Linking Writesonic as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Writesonic
beta: true
---

<!--
This is the user-facing posthog.com doc for the Writesonic source. It must be copied to the posthog.com
repo at contents/docs/cdp/sources/writesonic.md (served at /docs/cdp/sources/writesonic). It lives here
only because no posthog.com checkout was available when the source was implemented — it does not belong
in the posthog repo long-term. Once moved, run:
    python manage.py audit_source_docs --docs-dir ../posthog.com/contents/docs/cdp/sources
-->

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

[Writesonic](https://writesonic.com) tracks your brand's visibility in AI search — how often, how prominently, and in what context AI platforms like ChatGPT, Perplexity, and Google AI Overviews mention your brand (GEO, generative engine optimization). This connector pulls your daily performance metrics, raw AI answers with brand mentions, citations, keywords, and tracked configuration (topics, prompts, platforms, websites) into the PostHog Data warehouse, where you can join AI visibility with your product analytics.

## Prerequisites

You need a Writesonic account on a plan with API access to GEO data, with at least one website tracked. Your API key is revealed in the API dashboard of your Writesonic account.

## Adding a data source

<SourceSetupIntro />

You'll need:

- **API key** — from your Writesonic account's API dashboard. It authenticates every request through the `X-API-Key` header.
- **Site URL** — the URL of the tracked website, exactly as configured in Writesonic (e.g. `https://example.com`).
- **Project ID** (optional) — only needed to disambiguate when the same site is tracked in multiple Writesonic projects.

To sync more than one tracked site, add a separate Writesonic source per site.

## Sync modes

<SyncModes />

The performance and content tables (`performance_summary`, `performance_prompts`, `performance_answers`, `content_citations`, `content_keywords`) are exported one UTC day at a time and sync incrementally by date — the first sync backfills up to the last 365 days, and each later sync picks up from the last synced day. The configuration tables (`topics`, `platforms`, `websites`, `prompts`) are small and sync as full refresh.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **Invalid or inactive API key** — the key is wrong or was deactivated. Check the key in your Writesonic API dashboard and reconnect.
- **Site not found** — Writesonic couldn't match the configured site URL (and project ID, if set) to a tracked website in your account. Copy the URL exactly as it appears in your Writesonic workspace.
- **Plan does not include API access** — GEO data exports require a Writesonic plan with API access. Upgrade your plan and reconnect.

<TroubleshootingLink />
