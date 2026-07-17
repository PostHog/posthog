---
title: Linking Mixmax as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: MixMax
beta: true
---

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

[Mixmax](https://www.mixmax.com) is a sales-engagement and email-productivity platform for Gmail (sequences, meeting scheduling, snippets, and live email tracking). This connector syncs your Mixmax sequences, messages, snippets, rules, live feed, and related resources into the PostHog Data warehouse so you can join outreach activity with your product and revenue data.

## Prerequisites

Before connecting Mixmax, make sure you have:

- A Mixmax **Growth+ or Enterprise** plan — the API is not available on Free, and API access must be enabled on your workspace.
- An **API token**, created per user under **Settings ▸ Integrations ▸ API** in Mixmax. The token is scoped to the user that creates it, so it can only sync data that user can access.

## Adding a data source

<SourceSetupIntro />

You'll need:

- **API token** — from **Settings ▸ Integrations ▸ API** in your Mixmax account. The token is shown only once at creation, so copy it before leaving the page.

PostHog authenticates every request with this token (sent as the `X-API-Token` header).

## Sync modes

<SyncModes />

Mixmax's API does not expose a server-side "modified since" filter, so every table is synced as **full refresh** — each sync re-reads the resource and replaces the table. Because of Mixmax's fixed rate limit (120 requests per minute), prefer a modest sync frequency, especially for high-volume tables like the live feed.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **"Invalid Mixmax API token"** — the token is wrong, was revoked, or was never enabled. Create a new token under **Settings ▸ Integrations ▸ API** and reconnect.
- **API access not enabled** — the Mixmax API requires a Growth+ or Enterprise plan with the API feature enabled on your workspace. Confirm your plan and workspace settings, then reconnect.
- **Slow or throttled syncs** — Mixmax caps API usage at 120 requests per minute per user and IP address and is optimized for lightweight, real-time use rather than bulk export. Large tables can take a while to sync; lower your sync frequency if you hit rate limits.

<TroubleshootingLink />

<!--
STAGING NOTE (delete when relocating): this file is the user-facing posthog.com doc for the Mixmax
source. It is staged in this repo because no posthog.com checkout was available during implementation.
Before shipping, move it to the posthog.com repo at contents/docs/cdp/sources/mixmax.md (served at
/docs/cdp/sources/mixmax and /docs/data-warehouse/sources/mixmax), then run from the posthog repo:
python manage.py audit_source_docs --docs-dir ../posthog.com/contents/docs/cdp/sources
-->
