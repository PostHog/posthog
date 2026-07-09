# Batch import worker: e2e test plan

A phased plan for end-to-end tests of the batch import worker against realistic Mixpanel/Amplitude export API behavior.
Each phase is independently landable and sized for a single agent session.
Work through phases in order; within a phase, work items are ordered by dependency.

## Motivation: the failure class this must catch

A Mixpanel import paused with `Invalid JSON syntax ... expected value at line 1 column 1` at byte 0 of a chunk several MB into a day's part.
The source data was fine. Root cause:

1. The worker downloaded one day from Mixpanel's export API, parsed the first chunk, and committed the consumed decompressed-byte offset.
2. A deploy replaced the pod mid-part. The new pod re-downloaded the same day and got a **different byte stream** (repeat downloads of the same range returned different compressed sizes each time). Mixpanel's export output is not byte-stable between calls (event ordering shifts, late data arrives).
3. The saved offset, valid only for download #1's stream, landed mid-line in download #2. The first "line" of the chunk was a JSON fragment, so parsing failed at byte 0.

The failure mode family: **decompressed-byte offsets are only meaningful against the exact byte stream they were committed against**.
Re-downloads break that assumption unless remote staging pins the bytes.
No existing test exercises a re-download that returns different bytes, because all existing mocks are byte-stable.

## Architecture crib sheet (read this before touching code)

Data flow: `DataSource::get_chunk(key, offset, size)` → `newline_delim` JSONL parser → per-provider transform → `Emitter` → commit advances `PartState.current_offset` by `parsed.consumed`.

Key touchpoints, all under `rust/batch-import-worker/`:

| Thing | Where | Notes |
|---|---|---|
| Job fetch/parse loop | `src/job/mod.rs`, `select_and_fetch_next_chunk` | Deliberately DB-free: takes `&Mutex<JobState>`, `&Mutex<JobModel>`, `&dyn DataSource`, `&Arc<ParserFn>`, `chunk_size`. This is the harness entry point. |
| Job state | `src/job/model.rs`: `JobState { parts: Vec<PartState> }`, `PartState { key, current_offset, total_size }` | Plain constructible structs. `total_size: None` until the stream observes EOF. |
| Date-range source | `src/source/date_range_export.rs`, `DateRangeExportSource` | Downloads a `.raw` per interval key, streams decompression forward-only. `prepare_key` re-downloads if nothing is prepared (this is the re-download path). |
| Streaming decode | `src/extractor/mod.rs`, `StreamingReader`, `PlainGzipExtractor` (Mixpanel), `ZipGzipJsonExtractor` (Amplitude) | Forward-only, byte-addressed into the decompressed stream. |
| JSONL parser | `src/parse/format.rs`, `newline_delim` / `json_nd` | `consumed` always ends just past a newline, so chunk starts are line starts within one consistent stream. |
| Transforms | `src/parse/content/mixpanel.rs`, `amplitude.rs` | Mixpanel event UUID is deterministic UUIDv5 from `$insert_id` (`MIXPANEL_INSERT_ID_NAMESPACE`). `TransformContext` (`src/parse/content/mod.rs`) is hand-constructible; use `MockIdentifyCache` / `MockGroupCache` from `src/cache/mod.rs`. Do NOT build it via `AppContext` (that requires Postgres for the team-token lookup). |
| Emitters | `src/emit/mod.rs` | `FileEmitter::new(path, as_json, cleanup)` writes emitted events to disk: the no-service assertion channel. `KafkaEmitter` for the service-gated smoke test. |
| Remote staging | `src/source/mod.rs` `RemoteStaging`, `src/staging/` | Stages decompressed plaintext to the temp bucket so resumes do stable ranged reads. Config: `STAGING_BACKEND=temp_bucket`, `TEMP_BUCKET_*` in `src/config.rs`. |
| Existing tests | `tests/` | `date_range_export_streaming_test.rs` (resume with byte-stable mock: the gap), `temp_bucket_seaweedfs_integration_test.rs` (temp-bucket conventions), `person_processing_kafka_integration_test.rs` (Kafka skip-if-unreachable conventions), `tests/common/mod.rs` (shared helpers). |

## Conventions and guardrails (apply to every phase)

- Invoke the `/writing-tests` skill before writing any test. Every scenario below must catch a realistic regression no existing test catches; if an existing unit test already pins a behavior, do not duplicate it at e2e level.
- Follow the existing skip-if-unreachable pattern for service-gated tests (see the Kafka test's connectivity probe). Dependency-free tests must stay dependency-free.
- SeaweedFS, not MinIO, for any new object-storage need (repo-wide direction; the temp-bucket test already uses SeaweedFS).
- Run `cargo fmt` and `cargo clippy` after every Rust edit; run tests via `hogli test rust/batch-import-worker` (or `cargo test -p batch-import-worker`).
- Assertions compare emitted output against generated ground truth as a **set** of `(uuid, event, distinct_id, timestamp)`. Exactly-once means: nothing missing, nothing unexpected, and re-imported events produce identical UUIDs.
- Commit messages: `chore(batch-imports): ...`.

---

## Phase 1: Stateful mock export service + job-loop harness (no external services)

Goal: reproduce the incident in a test, plus cover the happy paths, without Postgres/Kafka/S3.

### 1a. Mock export service: `tests/common/mock_export.rs`

A hand-rolled axum server (bind an ephemeral port on localhost), because `httpmock` cannot serve stateful "different bytes per download attempt" responses.

- **Mixpanel mode**: GET endpoint taking `from_date`/`to_date` query params, basic auth (secret key as username, empty password), response body = gzip'd JSONL of Mixpanel-shaped events (`{"event": ..., "properties": {"time", "distinct_id", "$insert_id", ...}}`).
- **Amplitude mode**: same param shape, response body = a zip archive containing one or more `.json.gz` members of Amplitude-shaped events.
- **Deterministic event generator**: `fn events_for(seed, interval) -> Vec<Event>`; a test can independently regenerate ground truth. Do not use wall-clock time or global RNG; derive everything from the seed and the interval key.
- **Per-key, per-attempt behavior programming**, settable by the test:
  - `Reorder`: shuffle event order differently on each download attempt of a key (a seeded permutation keyed by attempt number). This is the incident behavior.
  - `LateData`: attempt N returns the events of attempt N-1 plus extra events.
  - `RateLimit { attempts, retry_after }`: first N attempts return 429 + `Retry-After`.
  - `NotFound` / `EmptyBody`: 404, or 200 with zero bytes.
  - `TruncatedGzip`: valid gzip header, body cut mid-stream.
- **Request log**: record every (key, attempt) so tests can assert download counts, e.g. "the restart caused exactly one re-download".

### 1b. Job-loop harness: `tests/common/harness.rs`

Drives the real pipeline in-process:

- Build a real `DateRangeExportSource` (correct extractor per provider) pointed at the mock server, staging under a `TempDir`.
- Build the real parser via `MixpanelEvent::parse_fn` / `AmplitudeEvent::parse_fn` with a hand-built `TransformContext` (mock caches, fixed team_id/token/job_id).
- Construct `JobState` with one `PartState { key, current_offset: 0, total_size: None }` per interval, and a minimal `JobModel` (plain struct; only the fields `select_and_fetch_next_chunk` touches matter).
- Loop `select_and_fetch_next_chunk` until `None`, emitting each parsed batch through `FileEmitter`, mirroring committed offsets into the harness's copy of `JobState` (the "database").
- `restart()` helper: drop the source (clearing prepared keys and staged `.raw` files, like a pod death), rebuild it fresh, and continue the loop from the persisted `JobState`. This is the honest simulation of the incident's pod replacement.
- Failure capture: the loop surfaces the first `Err` so tests can assert on the error chain (`UserError` message, offset, key).

### 1c. Scenarios: `tests/mixpanel_amplitude_e2e_test.rs`

| # | Scenario | Assertion |
|---|---|---|
| 1 | Mixpanel happy path, 3-day range, multiple chunks per part | Exactly-once vs ground truth; UUIDs are UUIDv5 of `$insert_id`; all parts done |
| 2 | Amplitude happy path (zip-gzip extractor, identify/group fan-out on) | Exactly-once; expected identify/group-identify events present |
| 3 | Restart mid-part, byte-stable export | Resume completes; exactly-once; exactly 2 downloads of the interrupted key |
| 4 | **Restart mid-part, `Reorder` export (the incident)** | Job errors with the JSON-parse-at-byte-0 shape; it must NOT complete "successfully" while silently skipping events. Assert the error, and assert no emitted-event loss/dupe up to the failure point |
| 5 | `RateLimit` then success | Backoff surfaces as `RateLimitedError`; retry completes exactly-once |
| 6 | `NotFound` day and `EmptyBody` day mixed into a range | Empty parts complete; other days exactly-once |
| 7 | Chunk-size sweep of scenario 1 (e.g. sizes that land mid-line, exactly on `\n`, exactly at line start; parameterize, do not copy-paste) | Exactly-once at every chunk size |

Notes for the implementing agent:

- Scenario 4's assertion is deliberately "fails loudly": today's correct behavior is to pause. If a later change makes resume-after-reorder safe (e.g. offset validation or automatic part restart), update this test to assert the new safe behavior, exactly-once included.
- Scenario 7 exists because `newline_delim`'s consumed arithmetic (remainder handling, leading-newline skip) is boundary-sensitive; a sweep is cheap here and pins it end to end.

---

## Phase 2: Remote staging e2e (SeaweedFS, service-gated)

Goal: **validate the S3 remote staging method as a whole**: prove it shields resumes from export nondeterminism (the fix we recommend to customers), that losing the staged object fails loudly, and that the S3 gzip source's staged path works too.

### What is already covered: do not duplicate

`tests/temp_bucket_seaweedfs_integration_test.rs` already validates the staging *plumbing* against real SeaweedFS:

- `TempBucketBackend` round trip: stage through the decompress pipeline, ranged reads (full / mid-slice / past-EOF), `cleanup_key` idempotence, job-prefix sweep.
- One `DateRangeExportSource` temp-bucket round trip: download once, stage, serve ranged reads, resume without re-download, sweep on cleanup.

Phase 2's job is the layer above: **end-to-end import correctness through the real job loop when the origin misbehaves**, asserted as exactly-once event output, not byte-level reads.

### Scenarios

New file `tests/remote_staging_e2e_test.rs`, following the existing conventions (SeaweedFS at localhost:8333, skip if unreachable but panic in CI, unique job-id prefix per test, cleanup at the end). Reuse the Phase 1 mock service and harness; wire the source with `.with_remote_staging(Some(RemoteStaging { ... }))` mirroring `DateRangeExportSourceConfig::create_source` in `src/job/config.rs`.

| # | Scenario | Assertion |
|---|---|---|
| 8 | `Reorder` mock + restart mid-part + `RemoteStaging` enabled | Resume succeeds reading staged plaintext; exactly-once; exactly 1 download of the key (the re-prepare re-attaches to the staged object instead of re-downloading). This is the direct validation that staging fixes the incident class |
| 9 | Staged object deleted mid-pause (simulate TTL sweep by deleting the object between restart and resume) with `Reorder` mock | Job re-downloads and fails loudly (scenario-4 behavior), never silently skips |
| 10 | ~~Restart mid-part while the part was only partially staged~~ **Dropped**: staged parts are multipart uploads completed only on success and aborted on any decode/ceiling error (`src/staging/temp_bucket.rs`), so a readable partial object cannot exist | n/a |
| 11 | Part whose decompressed size exceeds `max_plaintext_bytes` | Staging refuses with the user-facing cap error; job pauses; no partial staged object left behind |
| 12 | `GzipS3Source` with remote staging: gzip'd JSONL objects in SeaweedFS as the *origin* (standing in for a customer S3 bucket) + restart mid-part | Exactly-once through the job loop; staged plaintext survives the restart. Note: the existing `s3_gzip_minio_integration_test.rs` is MinIO-based and covers only the unstaged path; do not extend it, and do not add MinIO dependencies |
| 13 | Job completion sweeps the staging prefix; job *interruption* (release, not completion) keeps it | Assert bucket contents after each: empty prefix after `cleanup_after_job`, staged objects intact after `release_job_resources` |

Scenario 13 pins the resume contract that makes scenario 8 work: `release_job_resources` must keep remote staging (`src/source/date_range_export.rs` documents this) while terminal cleanup sweeps it.

---

## Phase 3 (optional): Full-worker lifecycle e2e (Postgres, service-gated)

Goal: cover the only layer Phases 1-2 skip: `JobModel`'s sqlx claim/lease/commit/pause path against the real `posthog_batchimport` table.

- Local dev Postgres runs on port 15432 (hogli dev stack). Skip if unreachable, same pattern as Kafka. Also skip if the DB already has claimable batch imports: `claim_next_job` claims *any* claimable row, and a test must never steal a developer's real local import.
- Insert a `posthog_batchimport` row with a Mixpanel source config pointed at the mock server, then drive `JobModel::claim_next_job` + the real `Job::process` loop in-process (preferable to spawning the binary: no env juggling, direct assertions). Secrets caveat: `JobSecrets::encrypt` expects pre-base64-encoded fernet keys while the claim path's `decrypt` encodes the raw configured keys internally, so seed with `encrypt(&[b64(raw_key)])`.
- Scenarios, implemented in `tests/job_lifecycle_postgres_test.rs`:
  - Claim → run to completion → status `completed`, state parts all done, one download per day.
  - Claim → `CorruptLine` parse failure → status `paused`, `display_status_message` contains the user-facing parse error with the date range suffix (the exact support-facing surface).
  - Resume: mirror the resume endpoint (`BatchImportViewSet.resume`) exactly, clearing `lease_id`/`leased_until`/backoff along with the status flip. Pausing deliberately keeps the worker's lease, so a bare `status = 'running'` update leaves the row unclaimable for up to 30 minutes.
  - `STAGING_BACKEND=temp_bucket` + `TEMP_BUCKET_*` via env → claimed job constructs the temp-bucket backend from the real envconfig path and completes through it (SeaweedFS-gated). This covers the env-to-backend wiring Phases 1-2 bypass; config *parse* errors are already unit-tested in `src/config.rs`.
- Deferred: the Kafka emit smoke test (the `KafkaEmitter` already has its own integration test; wiring it into the lifecycle loop adds little) and offset-reset-to-0 re-import (UUID determinism is already pinned in Phase 1).
- CI caveat: these tests require a Django-migrated Postgres with a team row, which the rust CI job does not currently provide, so they skip in CI and run against the local dev stack. Wiring a migrated database into rust CI is follow-up work.

---

## Phase 4 (stretch): hardening ideas, pick up only after 1-3 land

- Property-style fuzz: random seeds for event content (unicode in property values, multi-byte UTF-8 split across chunk boundaries: `newline_delim` has explicit handling worth pinning), random chunk sizes, random restart points. Keep runs bounded and deterministic per seed; log the seed on failure.
- Oversized single record (> chunk_size) → the "single record too large" user error.
- Double-compressed part (gzip magic at offset 0 of decompressed stream) → the compression-mismatch user error.
- A `Slow`/stall behavior in the mock to exercise request timeout handling (`extract_client_request_error`).

## Phase 5: real-endpoint contract testing (Mixpanel/Amplitude)

Goal: catch what no mock can anticipate - real API drift (auth quirks, response framing, compression changes, new fields, rate-limit behavior, export instability) - and give developers a one-command way to import real vendor data into local dev.

Principles:

- **Never in per-PR CI.** External dependencies, shared credentials, vendor rate limits, and multi-minute ingestion lag make these unfit to block merges. They run nightly and on demand.
- **Deterministic ground truth via an immutable seeded dataset.** Both vendors' export APIs serve historical data indefinitely; seed once, assert forever. Do not seed-then-assert in the same run (ingestion-to-export lag is minutes to hours and flaky).
- **Real response bytes in normal CI via record/replay.** Recording against the real APIs produces sanitized fixtures; replay tests parse them with the production parser on every PR, so "does our parser handle real Mixpanel/Amplitude output" is still continuously covered.

Work items, in order:

### 5a. Vendor test accounts and secrets

- PostHog-owned Mixpanel project and Amplitude project (free tiers suffice), used exclusively for this. Export credentials (Mixpanel API secret; Amplitude API key + secret key) stored as GitHub Actions secrets (see the managing-github-actions-secrets skill) and in the team vault for local use. Env names: `MIXPANEL_CONTRACT_TEST_API_SECRET`, `AMPLITUDE_CONTRACT_TEST_API_KEY`, `AMPLITUDE_CONTRACT_TEST_SECRET_KEY`.

### 5b. One-time seeding + checked-in manifest

- `scripts/seed_vendor_contract_data` (per-vendor): pushes a fixed synthetic dataset into a fixed **past** date range (e.g. 2020-03-01 to 2020-03-03) via Mixpanel's `/import` and Amplitude's batch upload API. Deterministic `$insert_id`s / `insert_id`s and distinct_ids (reuse the Phase 1 generator so ground truth is computable).
- The script also writes `tests/fixtures/vendor_manifest_{mixpanel,amplitude}.json`: the expected `(uuid, event, distinct_id)` set per day. Checked in; regenerated only if the dataset is ever re-seeded.

### 5c. Contract tests (opt-in, `#[ignore]`)

- `tests/vendor_contract_test.rs`: `#[ignore]`-d tests, skipped unless the credential env vars are set. Real `DateRangeExportSource` (real auth, real gzip framing) over the seeded range through the Phase 1 harness loop; assert exactly-once against the manifest.
- A byte-stability probe: download the same day twice and report (not assert) whether the bytes matched - drift telemetry for the instability class behind the incident.
- Run locally with `cargo test -p batch-import-worker --test vendor_contract_test -- --ignored`.

### 5d. Nightly workflow

- Scheduled GitHub Actions workflow (with `timeout-minutes`), non-blocking for PRs: runs the ignored contract tests with the secrets, posts failures to the owning team's alert channel. A red nightly means vendor drift or seeded-data loss - both worth a human look within a day, neither worth blocking merges.

### 5e. Record/replay fixtures

- A recording flag on the contract tests writes each day's raw export response body to `tests/fixtures/vendor_exports/` (already synthetic data, so nothing to sanitize beyond stripping any response headers).
- Replay tests (normal, not ignored, no network) feed the fixture bytes through the production extractor + parser and assert against the manifest - real vendor output shapes covered on every PR.
- Refresh fixtures by re-running the recorder manually when the nightly catches a format change.

### 5f. Developer ergonomics: ad hoc real imports into local dev

- Document (README section in this crate) the one-command path for importing real vendor data into a local PostHog: a small management command or script that inserts a `posthog_batchimport` row for the local team via `BatchImportConfigBuilder` (Mixpanel or Amplitude date-range source, the developer's own credentials from env), then runs the worker binary pointed at the dev stack. The Phase 3 test file is the reference for exactly what the row needs.
- This is the "does a real customer export actually import" smoke a developer runs before shipping source changes - with their own throwaway vendor account or the shared contract-test account.

## Suggested PR sequencing

1. PR 1: Phase 1 (mock service + harness + scenarios 1-7). This is the highest-value slice; scenario 4 alone would have caught the incident.
2. PR 2: Phase 2 (stacks on PR 1's harness).
3. PR 3: Phase 3.
4. Phase 4 items as opportunistic follow-ups.
5. Phase 5 in three PRs: seeding script + manifest (5a-5b, includes the one-time account setup), contract tests + nightly workflow (5c-5d), record/replay + dev docs (5e-5f).

## Verification checklist per PR

- `cargo fmt --check` and `cargo clippy` clean.
- `hogli test rust/batch-import-worker` green locally, with service-gated tests both skipping (services down) and passing (services up via `hogli up -d`).
- New tests fail when the behavior they pin is broken (spot-check by reverting the assertion target or injecting the bug, e.g. make the mock byte-stable in scenario 4 and confirm the test then demands success).
