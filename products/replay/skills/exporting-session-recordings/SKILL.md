---
name: exporting-session-recordings
description: >-
  Export a single session recording's raw data (recording blocks + ClickHouse
  metadata) to a downloadable zip, and download it. Staff-only. Use when asked to
  "export a session recording", "get the raw recording data", "download a replay
  export", "pull a recording for analysis/support", or to inspect recording block /
  canvas frame sizes offline. Explains why the MCP export tool only works for the
  active project, how to export a recording owned by any other team via the django
  admin portal (and how to build the right admin links), and how to download the
  archive (there is no download API or MCP tool).
---

# Exporting session recordings

Exporting bundles a recording's storage blocks plus its ClickHouse metadata
(`events.json`, `session-replay-events.json`) into a zip in object storage, for
offline analysis or support. It is **staff-only** and writes nothing back to the
recording.

## The one rule that matters: export team must own the recording

The export workflow fetches recording blocks and events **filtered by the team the
export is run for**. Block storage is keyed by team, and the events query filters
`team_id`. If that team does not own the `session_id`, the job still reaches
`status: complete` — but the zip is **empty** (zero blocks, empty `events.json`).
"Complete" means "the workflow ran", not "it found data".

The owning `team_id` is visible in the recording's storage path and in
`export_location` (`session_recording_exports/<team_id>/<session_id>/<uuid>.zip`).

## Which path to use

| The recording belongs to…  | Use                                                 |
| -------------------------- | --------------------------------------------------- |
| the **active MCP project** | the MCP tool `session-recording-export-create`      |
| **any other team**         | the **django admin portal** (build the links below) |

The MCP/API export only ever runs for the active project — there is deliberately
**no cross-team `team_id` parameter** (a token- or agent-reachable cross-tenant PII
export is too dangerous a capability to expose on the API surface). Cross-team
export stays behind interactive, staff-authenticated django admin. So: never call
the MCP tool with a `session_id` from another team — you'd just get an empty
archive. Send the user to the admin portal instead.

## Same-project recording (MCP)

1. `session-recording-export-create { session_id, reason }` — `reason` is audited;
   keep it specific. Returns a job with `status: pending`.
2. Poll `session-recording-export-get { id }` until `status` is `complete` or
   `failed`. Small recordings take seconds to a couple of minutes (it gathers blocks
   plus ClickHouse metadata). `failed` carries an `error_message`.
3. Download via admin (see below).

## Any other team's recording (admin portal — generate these links)

You need the **owning `team_id`** to build the links. If you only have a
`session_id`, get the team from the recording's project (or ask the user). Use the
correct region host — `us.posthog.com` or `eu.posthog.com` — matching where the
recording lives.

- **Trigger the export** (form takes `session_id` + `reason`):
  `https://<region>.posthog.com/admin/posthog/team/<team_id>/export-replay/`
- **See exports + download buttons** for that team:
  `https://<region>.posthog.com/admin/posthog/team/<team_id>/export-history/`
- **Direct download** of one archive once complete:
  `https://<region>.posthog.com/admin/posthog/team/<team_id>/download-export/<export_id>/`

Hand the user the export-replay link to start it, then the export-history link to
download. This is the right tool for "export a customer's recording" — present the
links rather than attempting it via MCP.

## Downloading the archive

There is **no download API endpoint and no MCP download tool** — the export only
exposes a storage key. Downloads go through django admin (the links above). The
download view streams the zip straight from the replay-v2 S3 bucket as
`export-<session_id>.zip`; the admin pod holds the prod credentials, so a local dev
or agent session cannot `aws s3 cp` the key itself.

## Gotchas

- **Empty-but-complete** is the failure mode to watch for — see the team rule. If an
  archive is unexpectedly tiny, the export almost certainly ran for the wrong team.
- **Expiry:** exports older than 7 days report `is_expired: true` and their data may
  be purged. Re-export rather than relying on an old job.
- **Stuck `running`:** a failed export used to sit in `running` forever; a new export
  now reaps any export still `pending`/`running` past ~48h to `failed`, so old wedged
  rows clear themselves. Don't read a long-stale `running` as "still working".
- **Large recordings:** multi-GB recordings (tab-left-open-for-days outliers) are not
  practical to export — the pipeline base64s every block through Redis and zero-pads
  to byte offsets on disk. Prefer recordings in the hundreds-of-MB range.
- **Reason is audit-logged** and surfaced in admin — write it for a human reviewer.
