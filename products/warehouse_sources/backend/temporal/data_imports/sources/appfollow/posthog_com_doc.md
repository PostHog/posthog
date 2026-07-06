---
title: Linking AppFollow as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Appfollow
beta: true
---

<!--
This is the user-facing posthog.com doc for the AppFollow source. It must be copied to the posthog.com
repo at contents/docs/cdp/sources/appfollow.md (served at /docs/cdp/sources/appfollow). It lives here
only because no posthog.com checkout was available when the source was implemented — it does not belong
in the posthog repo long-term. Once moved, run:
    python manage.py audit_source_docs --docs-dir ../posthog.com/contents/docs/cdp/sources
-->

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

[AppFollow](https://appfollow.io) aggregates App Store and Google Play data for app analytics, review
management, and app store optimization. This connector pulls your tracked apps, their reviews, and their
rating history into the PostHog Data warehouse, where you can join them with product analytics, build
insights, and monitor review sentiment over time.

## Prerequisites

You need an AppFollow account with API access. Only an Account Owner or Admin can generate an API token,
on the [API management page](https://watch.appfollow.io/settings/api) in your AppFollow account.

AppFollow bills API usage against a credit balance — reviews and ratings requests cost more credits than
the account and app-listing endpoints — and rate-limits to 1000 requests/hour per token and 10,000
requests/hour per account. The reviews and ratings tables can therefore consume a meaningful amount of
credits on their first (full history) sync.

## Adding a data source

<SourceSetupIntro />

Paste the API token you generated on the AppFollow API management page. It authenticates every request
through the `X-AppFollow-API-Token` header.

## Sync modes

<SyncModes />

The `reviews` table syncs incrementally on each review's last-modified timestamp, and `ratings_history`
syncs incrementally by date, so after the first backfill only new and changed rows are fetched. The
`app_collections`, `app_lists`, and `users` tables are small and sync as full refresh.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

The `reviews` and `ratings_history` tables are queried per app using the app's store `ext_id`, which is
discovered by walking your collections (`app_collections`) and their apps (`app_lists`). Because those
requests cost credits, `ratings_history` and `users` are off by default — enable them in the table
picker if you want them.

## Troubleshooting

- **Invalid API token** — the token is wrong or was revoked. Generate a new one on the AppFollow API
  management page and reconnect.
- **Out of API credits** — your AppFollow account has exhausted its credit balance. Wait for the balance
  to reset or upgrade your plan, then retry the sync.

<TroubleshootingLink />
