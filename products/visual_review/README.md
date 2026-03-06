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

**Run** — one CI execution. Created from a manifest of snapshot identifiers + hashes. Holds summary counts (changed/new/removed), commit SHA, branch, PR number, and a status lifecycle: `pending → processing → completed` (or `failed`).

**RunSnapshot** — one screenshot within a run. Links current and baseline artifacts, holds the computed result (`unchanged`, `changed`, `new`, `removed`) and the human review state (`pending`, `approved`). The result is set at creation from hash comparison; the diff artifact and pixel metrics come later from async processing.

**Supersession** — when a new run is created for the same (repo, branch, run_type), older runs get a `superseded_by` pointer. This prevents approving stale runs without GitHub API polling — the DB knows what's current.

## The flow

```text
Developer pushes PR
       │
       ▼
CI captures screenshots, runs `vr submit`
  - scan directory for PNGs
  - hash each (RGBA bitmap → SHA-256)
  - read baseline YAML from repo
  - POST /runs with manifest
  - receive presigned S3 upload URLs (only for hashes the backend doesn't have)
  - upload directly to S3
  - POST /runs/{id}/complete
       │
       ▼
Backend queues async diff (Celery)
  - download baseline + current from S3
  - pixel diff with per-channel threshold (Pillow)
  - upload diff overlay artifact
  - mark run completed
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

Summary counts (changed/new/removed) are computed synchronously at run creation via hash comparison — the UI always has numbers even before async diffs finish.

## CLI

The `vr` CLI (`cli/`) is a TypeScript tool that bridges CI and the backend. It's deliberately capture-agnostic: it works with any tool that produces PNGs (Storybook, Playwright, Cypress, etc.).

Snapshot ID is derived from the PNG filename: `button--primary.png` → `button--primary`. Explicit and predictable.

The CLI uploads directly to S3 via presigned POST URLs — the backend never proxies image bytes. Exit code: 0 if clean, 1 if changes need review.

Commands: `vr submit` (main flow), `vr verify` (local baseline check without API).

## Current state

Working end to end: CI upload → async diff → GitHub Check → web review → approve → baseline commit → clean re-run. Multi-repo per team, snapshot change history across runs, run supersession, GitHub commit status checks on transitions.

**Known gaps:**

- `complete_run` silently skips missing uploads instead of validating they arrived
- Approval doesn't validate that submitted identifiers belong to the run or that hashes match
- Removed snapshots are detected but the YAML writer only merges, never deletes entries
- Frontend error toast swallows structured error codes (`sha_mismatch`, `stale_run`) instead of showing tailored messages
- `complete_run` isn't idempotent — calling twice queues the diff task twice

These are correctness gaps, not architecture problems. The core model is sound.

**Not yet built:**

- Sharding/merging across parallel CI jobs
- Multiple viewports or themes per snapshot (can be encoded in identifiers)
- Retention / cleanup of old runs and artifacts
- Webhook-driven run creation (currently CLI-initiated only)
