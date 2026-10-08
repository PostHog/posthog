---
title: Linking Twelve Labs as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: TwelveLabs
---

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

Sync your [Twelve Labs](https://www.twelvelabs.io) video understanding library into PostHog. This
connector imports your indexes, the videos in each index, the video indexing tasks that track the
upload and indexing lifecycle, and the transcriptions of your video and audio assets, so you can
analyze library growth, indexing throughput, indexing failures, and spoken content alongside the rest
of your data.

## Prerequisites

You need a Twelve Labs account and an API key. Any plan tier works, but be aware that free plans have
daily request caps that can slow the sync of very large libraries.

## Adding a data source

<SourceSetupIntro />

You need your **Twelve Labs API key**. You can create one from the
[API key page](https://playground.twelvelabs.io/dashboard/api-key) in your Twelve Labs dashboard. Paste
it into the API key field when connecting the source.

## Sync modes

<SyncModes />

`indexes` and `tasks` support incremental sync (via the server-side `updated_at` filter) and are
recommended for ongoing syncs. `videos` is nested per index and syncs by full refresh; it is disabled
by default because fanning out one request per index can consume a meaningful share of a free plan's
daily request quota. Enable it when you need per-video metadata.

`asset_transcriptions` works the same way: it makes one request per video or audio asset, syncs by
full refresh, and is disabled by default. Each row holds the transcription status plus its sentences
and speaker turns. Assets without a transcription are skipped.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

If the connection fails with an authorization error, confirm your API key is active in the Twelve Labs
dashboard and has not been revoked. If a large library syncs slowly, it is most likely being throttled
by your plan's daily request cap; syncing fewer tables or upgrading your plan will help.

<TroubleshootingLink />
