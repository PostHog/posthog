# Visual Review

Visual regression testing that keeps baselines in git.

CI captures screenshots, the backend diffs them against committed baselines, developers review and approve changes in a web UI, and a bot commits the updated baselines back to the PR.
No external baseline service — the repo is the source of truth.

## The idea

Most visual regression tools either need a full SaaS subscription or maintain baselines in a separate store that drifts from the code.
Visual Review takes a different approach: the baseline is a `.snapshots.yml` file checked into the repo, containing a map of snapshot identifiers to content hashes.
When a developer approves visual changes, the tool commits an updated YAML to the PR branch.
When CI runs again, hashes match, the check goes green, and the PR is ready to merge.

This means baselines follow the same branching, merging, and review workflow as code.
No sync problems, no "baseline service went down", no mystery diffs from someone else's approval on a different branch.

## Concepts

**Repo** — a visual review project within a PostHog team. Usually maps 1:1 to a GitHub repository. Holds configuration like which baseline file paths to use per run type.

**Artifact** — a PNG stored by the SHA-256 hash of its RGBA bitmap data. Content-addressed: identical pixels produce identical hashes, regardless of PNG compression or metadata. Two runs producing the same screenshot share one artifact. Storage is S3, scoped per repo.

**Run** — one CI execution. Created with a manifest of snapshot identifiers + hashes (or empty for shard flow). Holds summary counts (changed/new/removed), commit SHA, branch, PR number, and a status lifecycle: `pending → processing → completed` (or `failed`). Snapshot classification (changed/new/unchanged/removed) happens at `complete_run` time when the backend fetches the baseline from GitHub.

**RunSnapshot** — one screenshot within a run. Links current and baseline artifacts, holds the computed result (`unchanged`, `changed`, `new`, `removed`) and the human review state (`pending`, `approved`). Snapshots are stored with a provisional result at creation; final classification happens at `complete_run` time when the backend compares against the GitHub baseline. The diff artifact and pixel metrics come later from async processing.

**Supersession** — when a new run is created for the same (repo, branch, run_type), older runs get a `superseded_by` pointer. This prevents approving stale runs without GitHub API polling — the DB knows what's current.

## The flow

### Single-command flow (`vr submit`)

```text
Developer pushes PR
       │
       ▼
CI captures screenshots, runs `vr submit`
  - scan directory for PNGs
  - hash each (RGBA bitmap → SHA-256)
  - POST /runs with full manifest (identifiers + hashes)
  - receive presigned S3 upload URLs (only for hashes the backend doesn't have)
  - upload directly to S3
  - POST /runs/{id}/complete
       │
       ▼
Backend completes the run
  - fetch baseline YAML from GitHub (branch + merge-base for healing)
  - classify each snapshot against baseline (unchanged/changed/new)
  - tolerated hash cache: skip diffing for known sub-threshold pairs
  - detect removals: baseline identifiers missing from RunSnapshot rows
  - verify uploads, create artifact records, link to snapshots
  - two-tier diff (Celery): pixel diff → SSIM for tall-page dilution
  - post GitHub Check (pass/fail)
       │
       ▼
Developer opens the web UI
  - runs list, filterable by review state (needs review / clean / processing / stale)
  - run detail: thumbnail strip of changed snapshots, side-by-side diff viewer
  - click "Approve" → POST /runs/{id}/approve
       │
       ▼
Backend commits updated .snapshots.yml to PR branch (GitHub API)
       │
       ▼
CI re-runs → hashes match → check passes → PR ready to merge
```

### Shard flow (`vr run create/upload/complete`)

For parallel CI jobs that each capture a subset of screenshots:

```text
CI matrix starts
       │
       ▼
Setup job: `vr run create --type storybook`
  - creates an empty pending run, outputs run_id
       │
       ▼
Each shard: `vr run upload --run-id <id> --dir ./screenshots`
  - hash PNGs, POST /runs/{id}/add-snapshots
  - upload missing artifacts to S3
  (shards run in parallel, idempotent per identifier)
       │
       ▼
Final job: `vr run complete --run-id <id>`
  - backend fetches baseline from GitHub
  - classifies all snapshots, detects removals
  - triggers diffs, posts GitHub Check
  - exit code gates the pipeline (1 = changes need review)
```

The backend is the source of truth for baselines — it fetches the `.snapshots.yml` from GitHub at `complete_run` time. The CLI no longer sends baseline hashes; it only sends snapshot identifiers and content hashes.

## CLI

The `vr` CLI (`cli/`) is a TypeScript tool that bridges CI and the backend. It's deliberately capture-agnostic: it works with any tool that produces PNGs (Storybook, Playwright, Cypress, etc.).

Snapshot ID is derived from the PNG filename: `button--primary.png` → `button--primary`. Explicit and predictable.

The CLI uploads directly to S3 via presigned POST URLs — the backend never proxies image bytes. Log output goes to stderr so stdout stays clean for machine-readable output (e.g. run IDs for CI capture).

### Commands

**`vr submit`** — single-command flow. Scans a directory, hashes PNGs, creates a run with full manifest, uploads, and completes. Without `--auto-approve`, exits 1 if unapproved changes are detected (gating). With `--auto-approve`, approves everything, writes the signed baseline, and exits 0.

**`vr verify`** — local baseline check without API.

**`vr run create`** — creates an empty pending run, outputs the run ID to stdout. Call once before shards.

**`vr run upload`** — per-shard: hashes PNGs in a directory, sends identifiers + hashes via `add-snapshots`, uploads missing artifacts.

**`vr run complete`** — triggers completion (classification, removal detection, diffs). Same exit code semantics as `vr submit`: exits 1 on unapproved changes, 0 if clean or `--auto-approve` is set.

## Current state

Working end to end: CI upload → async diff → GitHub Check → web review → approve → baseline commit → clean re-run. Multi-repo per team, snapshot change history across runs, run supersession, GitHub commit status checks on transitions.

**Tolerated hashes** — when the two-tier diff classifies a snapshot as below-threshold noise, it caches the `(identifier, baseline_hash, alternate_hash)` tuple.
Future runs skip diffing entirely for cached pairs.
Developers can also manually tolerate a snapshot from the UI.

**Quarantine** — known-flaky identifiers can be quarantined per repo and run type.
Quarantined snapshots are still captured and diffed but excluded from gating.

**Known gaps:**

- Frontend error toast swallows structured error codes (`sha_mismatch`, `stale_run`) instead of showing tailored messages

**Not yet built:**

- Retention / cleanup of old runs and artifacts
- Server-side thumbnailing for the snapshot strip
- Webhook-driven run creation (currently CLI-initiated only)
