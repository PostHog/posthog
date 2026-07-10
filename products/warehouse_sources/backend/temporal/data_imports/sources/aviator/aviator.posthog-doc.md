<!--
This is the user-facing source documentation. It belongs in the posthog.com repo at
contents/docs/cdp/sources/aviator.md (served at /docs/cdp/sources/aviator). It is kept here only
because a posthog.com checkout was not available when the source was implemented — copy it across and
delete this file from this repo. Run `python manage.py audit_source_docs --docs-dir <posthog.com>/contents/docs/cdp/sources`
once it lands.
-->

---
title: Linking Aviator as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Aviator
beta: true
---

import SourceSetupIntro from "../_snippets/source-setup-intro.mdx"
import SyncModes from "../_snippets/sync-modes.mdx"
import TroubleshootingLink from "../_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../_snippets/alpha-release.mdx"

<AlphaRelease />

[Aviator](https://www.aviator.co/) is a developer productivity suite built around a merge queue for GitHub.
This connector pulls your Aviator data — repositories, daily merge-queue analytics, currently queued pull
requests, live queue depth, and merge-queue config history — into the PostHog Data warehouse so you can
join it with your product and engineering data.

## Prerequisites

You need an Aviator account and a user access token. The token inherits your account's repository access,
so no additional scopes are required.

## Adding a data source

<SourceSetupIntro />

Aviator authenticates with a user access token (it starts with `av_uat_`). Create one from your
[Aviator account settings](https://www.aviator.co/) and paste it into the **API token** field.

## Sync modes

<SyncModes />

Only **Merge queue analytics** supports incremental sync — it advances a UTC date window (`start`/`end`)
and re-reads a short trailing window each run, because recent daily aggregates can be revised. The other
tables are current-state snapshots or small lists with no server-side timestamp filter, so they sync as
full refresh.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **401 Unauthorized** — the API token is invalid or has been revoked. Create a new user access token in
  your Aviator account settings and reconnect.
- **403 Forbidden** — the token is valid but does not have access to a repository's data. Check the
  token's repository access in Aviator and reconnect.

<TroubleshootingLink />
