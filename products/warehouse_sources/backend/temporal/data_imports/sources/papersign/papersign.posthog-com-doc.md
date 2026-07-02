<!--
This file belongs in the posthog.com repo at:
  contents/docs/cdp/sources/papersign.md
It is checked in here only because this PR was authored without a posthog.com checkout.
Move it to posthog.com (verbatim, minus this comment) and run:
  python manage.py audit_source_docs --docs-dir ../posthog.com/contents/docs/cdp/sources
-->
---
title: Linking Papersign as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Papersign
beta: true
---

import SourceSetupIntro from "../_snippets/source-setup-intro.mdx"
import SyncModes from "../_snippets/sync-modes.mdx"
import TroubleshootingLink from "../_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../_snippets/alpha-release.mdx"

<AlphaRelease />

[Papersign](https://paperform.co/products/papersign/) is Paperform's e-signature product.
Linking it as a source syncs your signing documents, folders, and spaces into the PostHog Data
warehouse, so you can join signing activity with the rest of your product and revenue data.

## Prerequisites

- A paid Paperform plan (Standard or Business tier) — the Papersign API is only available on paid plans.
- A Paperform API key, which you generate on your Paperform account page.

## Adding a data source

<SourceSetupIntro />

You'll need a Paperform API key:

1. Sign in to Paperform and open your [API keys page](https://paperform.co/account/developer/api-keys).
2. Create a new API key and copy it.
3. Paste it into the **API key** field when connecting Papersign in PostHog.

The key has full account access — Paperform does not offer per-resource scopes, so a single key can
read all of your Papersign documents, folders, and spaces.

## Sync modes

<SyncModes />

All Papersign tables sync via **full refresh**. Papersign documents change status over their lifetime
(a document moves from draft through in progress to completed, canceled, expired, or rejected), and the
API does not expose a reliable server-side "last updated" filter, so each sync re-reads the current
state of every record to keep status changes up to date.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **Invalid API key.** Double-check the key on your Paperform account page and reconnect — keys can be
  revoked and regenerated at any time.
- **Papersign API access errors (403).** The Papersign API requires a paid Paperform plan. If your plan
  is downgraded, syncs will fail until Papersign API access is restored.
- **Rate limiting.** The Paperform API is rate limited per minute. PostHog automatically backs off and
  retries, so transient `429` responses resolve on their own.

<TroubleshootingLink />
