---
name: exporting-session-recordings
description: >-
  Export a single session recording's raw data (recording blocks + ClickHouse
  metadata) to a downloadable zip, and download it. Staff-only, via the django
  admin portal. Use when asked to "export a session recording", "get the raw
  recording data", "download a replay export", "pull a recording for
  analysis/support", or to inspect recording block / canvas frame sizes offline.
  Explains the team-ownership rule, how to build the admin export / download links
  for the owning team, and that there is no export or download API/MCP tool.
---

# Exporting session recordings

Exporting bundles a recording's storage blocks plus its ClickHouse metadata
(`events.json`, `session-replay-events.json`) into a zip in object storage, for
offline analysis or support. It is **staff-only** and writes nothing back to the
recording.

There is **no export API or MCP tool** — a recording export is a cross-tenant,
token/agent-reachable PII export, which is too dangerous to expose on the
programmatic surface. Exporting (and downloading) is done **only** through the
django admin portal, under interactive staff auth. Your job is to hand the user
the right admin links.

## The one rule that matters: export from the team that owns the recording

The export workflow fetches recording blocks and events **filtered by the team you
run the export for** (block storage is keyed by team; the events query filters
`team_id`). If you run it for the wrong team, the job still reaches
`status: complete` — but the zip is **empty** (zero blocks, empty `events.json`).
"Complete" means "the workflow ran", not "it found data".

So always export from the **owning team's** admin page. The owning `team_id` is
visible in the recording's storage path and in `export_location`
(`session_recording_exports/<team_id>/<session_id>/<uuid>.zip`).

## Exporting via the admin portal (generate these links)

You need the **owning `team_id`** to build the links. If you only have a
`session_id`, get the team from the recording's project (or ask the user). Use the
correct region host — `us.posthog.com` or `eu.posthog.com` — matching where the
recording lives.

- **Trigger the export** (form takes `session_id` + `reason`; `reason` is audited):
  `https://<region>.posthog.com/admin/posthog/team/<team_id>/export-replay/`
- **See exports + download buttons** for that team:
  `https://<region>.posthog.com/admin/posthog/team/<team_id>/export-history/`
- **Direct download** of one archive once `status` is `complete`:
  `https://<region>.posthog.com/admin/posthog/team/<team_id>/download-export/<export_id>/`

Hand the user the export-replay link to start it, then the export-history link to
poll status and download. A small recording takes seconds to a couple of minutes
(it gathers blocks plus ClickHouse metadata); the export-history page shows
`pending` / `running` / `complete` / `failed`.

## Downloading the archive

The download view (export-history / download-export links above) streams the zip
straight from the replay-v2 S3 bucket as `export-<session_id>.zip`. `export_location`
is only a storage key, not a URL. The admin pod holds the prod credentials, so a
local dev or agent session cannot `aws s3 cp` the key itself — the user downloads
from the admin page in their browser.

## Gotchas

- **Empty-but-complete** is the failure mode to watch for — see the team rule. If an
  archive is unexpectedly tiny, the export almost certainly ran from the wrong
  team's admin page.
- **Expiry:** exports older than 7 days report `is_expired: true` and their data may
  be purged. Re-export rather than relying on an old job.
- **Stuck `running`:** a failed export used to sit in `running` forever; a new export
  now reaps any export still `pending`/`running` past ~48h to `failed`, so old wedged
  rows clear themselves. Don't read a long-stale `running` as "still working".
- **Large recordings:** multi-GB recordings (tab-left-open-for-days outliers) are not
  practical to export — the pipeline base64s every block through Redis and zero-pads
  to byte offsets on disk. Prefer recordings in the hundreds-of-MB range.
- **Reason is audit-logged** and surfaced in admin — write it for a human reviewer.
