# Recording exports to a customer's S3 bucket

A staff-run, one-off export of a team's session recordings into an S3 bucket the customer owns.
Customers use it to keep recordings past their retention period, for example for litigation.
The customer pays for the export, so every run starts from a quote.

Each session becomes one `.phrec` file.
The file playback page in Replay plays it back (Replay → file playback, then load the file).
It plays one session at a time, with no event timeline and no search.

## How a run works

1. `export_recordings_to_s3 --quote` measures the selection in ClickHouse and prices it.
   It stores the quote in our object storage under `session_recording_exports/quotes/<quote_id>.json`.
   A quote is valid for 7 days.
2. `export_recordings_to_s3 --quote-id` starts the `export-recordings` workflow on the session replay task queue.
   The date range and any session list come from the quote, so the run exports what the quote priced.
3. The workflow splits each day into `--shards-per-day` shards by session ID hash.
   It runs at most `--max-parallel-shards` shards at once, oldest day first, so the sessions closest to expiry go first.
4. Each shard lists its sessions in `session_replay_events`, fetches every block from recording-api (decrypted, still snappy-compressed) and writes the session file.
   A shard checkpoints through its heartbeat every 500 sessions, so a retry resumes there.
5. A last activity writes `quote.json` and `summary.json` next to the manifests.
   `summary.json` exists only when the run finished.

Sessions deleted between the quote and the run drop out and show as `deleted_before_run` in the summary.
Sessions that expire during the run get the `expired` status.

## Bucket layout

```text
{prefix}/{team_id}/{yyyy-mm-dd}/{session_id}.phrec          one file per session, by session start day (UTC)
{prefix}/{team_id}/manifests/{run_id}/{day}-{shard}-{part}.jsonl
{prefix}/{team_id}/manifests/{run_id}/quote.json
{prefix}/{team_id}/manifests/{run_id}/summary.json
```

Each manifest line has `session_id`, `distinct_id`, `status` (`exported`, `deleted`, `expired` or `missing`), `start_time`, `end_time`, `key`, `bytes`, `sha256` and `block_count`.
`sha256` covers the whole file, so the customer can check each object against it.

## File format

```text
PHREC1\n                       magic
{header JSON}\n                one line: version, session_id, team_id, distinct_id, start_time, end_time,
                               person, viewports, exported_at, block_count
[u32 big-endian length][block] repeated, in playback order
```

Each block is the stored block, decrypted and otherwise unchanged (snappy-compressed JSON lines).
The header carries viewports because file playback has no events to read them from.

## What the customer sets up

The export writes through the same role-based AWS S3 integration that S3 batch exports use.
The customer adds it in the project with the AWS S3 setup modal ("assume IAM role"), which lists the trust policy requirements:

- The role trusts PostHog's batch export role for the region.
- The trust policy requires `sts:ExternalId` equal to `posthog-<organization id>`.
  PostHog refuses a role that does not enforce it.
- The role allows `s3:PutObject` and `s3:AbortMultipartUpload` on the bucket and prefix.
- With `--kms-key-id`, the role also allows `kms:GenerateDataKey` and `kms:Decrypt` on the key, and the key policy allows the role.
  Pass the flag even when the bucket encrypts with that key by default: the session policy caps the role to the actions it lists.

The export never reads or lists the bucket.

## Cost

The quote prices our side at AWS list prices: GET requests (Standard and Glacier Instant Retrieval), Glacier IR retrieval, cross-region transfer and worker compute.
Block files outside the 30-day tier move to Glacier IR after 30 days, so older data costs more to read.
PUT requests and storage are on the customer's AWS bill.
The quote prints our cost, not a price. The price is a sales decision.
