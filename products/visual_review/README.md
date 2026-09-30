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

### Retention

Two daily Celery tasks delete data that can no longer be used: `sweep visual review runs`, and an hour later `sweep visual review artifacts`.
The windows and the reasons behind them are constants in `backend/logic/retention.py`.

- Superseded runs on PR branches go after 3 days, on the default branch after 180 days.
  A run without a PR number counts as default-branch history, because we do not record a repo's real default branch.
- A PR branch with no run in 30 days loses its latest runs too, except the repo's newest completed full run per run type, which is the last row naming the committed baseline hashes.
  Merge-queue branches (`trunk-merge/`) hold one batch run each and go after 7 days.
- A run that an active quarantine names as its source stays, so the quarantine can still show where it came from.
- Artifacts go by reference, never by age: content addressing means one upload backs every later run with the same pixels.
  An artifact goes when no snapshot of the repo points at it or names its hash, no artifact uses it as a thumbnail, and it is over 7 days old.
- Rows go before objects, and run registration and the delete share a per-repo lock, so a run is never told an artifact exists that the sweep then removes.
  An artifact row is what makes the CLI skip an upload, so a row without its object is the one state to avoid; a leaked object only costs storage.
- A story-to-file map goes when the sweep deletes the last run that names it.
- Each invocation is capped by rows and by a time budget, so a backlog drains over days.
  The budget stays below the time a deploy gives a busy worker to finish, so a deploy cannot kill a sweep.
  Artifacts have their own task and budget, so a backlog of runs cannot use up the time the artifact sweep needs.

### Weekly debt digest

Every Monday morning a Celery task, `send visual review debt digests`, posts each team a Slack reminder about the visual review debt it still carries.
The digest is stateless: every Monday both conditions below are evaluated from current data, and nothing is stored about what was sent.
An item repeats every week while it stands, and stops the week the condition no longer holds.

Each message is Block Kit.
The lead names the team and the week, and counts each condition that has items, with buttons to the repository's flakiness overview and its snapshots.
Under it, one thread reply per condition that has items: a line saying what to do about that condition, then one section per item with the single action that resolves it on a button beside it.
Theme variants of one story list as one entry when the reader would see the same facts for each.
A merged expiring quarantine links to the flakiness page searched to that story, and a merged unowned file keeps its file button.
Pile-ups never merge, because each theme variant carries its own toleration count.
The last reply says when the next digest comes.
A team that owns nothing gets no message at all.

Two conditions, and nothing else:

- **Quarantine expiring.**
  An active quarantine that runs out inside `FLAKINESS_EXPIRY_SOON_DAYS`, plus one day.
  The extra day is overlap: two weekly runs can fall slightly more than seven days apart, and a quarantine expiring in that gap would otherwise never be reported.
  The flakiness page keeps the plain seven days.
  It clears when somebody extends it past the window, lifts it, or lets it lapse.
- **Tolerated N times in 30 days.**
  `VARIANT_PILEUP_MIN` or more tolerations by a person or agent in the last `TOLERATION_PILEUP_WINDOW_DAYS`, with no quarantine already covering the identity.
  It matches the manual half of the rule the Tolerate dialog uses to suggest a quarantine.
  The count spans every baseline.
  A flaky story's baseline often moves between tolerations, and a count scoped to the current baseline would drop to zero at each move while the tolerations go on.
  Automatic tolerations do not count: they absorb renderings under the diff thresholds, which never block anybody.
  It clears when the tolerations age out of the window.
  Reminders about retained exceptions repeat until they are removed or no longer apply.

Attribution runs through the story index of the newest default-branch Storybook run, and then through `owners.yaml`.
`vr run upload --storybook-index <index.json> --storybook-root <dir>` turns the build's `index.json` into a story-to-file map, and each default-branch run records the map's SHA-256 in `metadata["story_index_hash"]`.
The map is stored once per distinct content, under `visual_review/<repo_id>/story-index/<hash>.json`, and uploaded only when the store does not hold that hash yet.
A reader accepts the stored bytes only when they hash to their name.
A snapshot identifier is a story id plus the theme, the browser when it is not chromium, and the viewport width for a story that snapshots several.
The full story id is looked up first and the width suffix is only stripped when that misses, because a story can be named after a width.
The parsed map is cached by its hash, so a cached copy is never stale.
Nothing is guessed from the identifier: a story name is not a path.
Only Storybook runs are attributed today.

Three outcomes have no owning team, and the digest keeps them apart:

- **Nobody owns the file.** The story maps to a file, and no owners entry covers it. Add one for the path, which the message carries.
- **The story is not in the index.** It moved, was renamed, was deleted, or it only exists on a branch.
- **Ownership could not be worked out.** The newest default-branch run recorded no story index, the stored map could not be read, or the run type is not supported yet.

All three go to whoever owns `products/visual_review/`, in a message of their own rather than inside the digest those maintainers get for what they own.
Holding an item until a team takes it is not owning it, and the wording says so.
The message goes out only when at least one item asks somebody to act.
The first two outcomes are listed, each with a button to the file or the snapshot.
The third is only counted in the footer, because it asks the reader for nothing; the reasons go to the log instead.
When nobody owns `products/visual_review/` either, the items are logged and dropped rather than posted somewhere arbitrary.

Routing goes to the team's `notifications` channel in the repository's root `owners.yaml` registry, under the `visual_review` producer.
A team opts out with `notifications: {visual_review: false}` under its entry.
A shared Slack channel is refused, so a name match never carries an internal reminder out of the workspace.

The digest is off for a repository until `debt_digest_enabled` is set on it.
Set it through the repo API (`PATCH /api/projects/:team_id/visual_review/repos/:id/`), the `visual-review-repos-partial-update` MCP tool, or Django admin.
The beat task runs on Monday morning and fans out only to the repositories that are on.
A repository that owes nothing posts nothing.

`./manage.py visual_review_debt_digest --repo owner/name [--mode preview]` runs one repository by hand on any day, whatever `debt_digest_enabled` says, because a run somebody starts is already a decision to send it.
`--mode preview`, the default, prints and logs the plain text behind every message without posting.
`--mode live` posts.

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
  - diff (Celery): row alignment absorbs small vertical shifts, then pixel diff → SSIM for tall-page dilution
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
  - with --storybook-index: send the story-to-file map's hash, upload the map if missing
  (shards run in parallel, idempotent per identifier)
       │
       ▼
Final job: `vr run complete --run-id <id>`
  - backend fetches baseline from GitHub
  - classifies all snapshots, detects removals
  - triggers diffs, posts GitHub Check
  - exit code gates the pipeline (1 = changes need review, 2 = command failed)
```

The backend is the source of truth for baselines — it fetches the `.snapshots.yml` from GitHub at `complete_run` time. The CLI no longer sends baseline hashes; it only sends snapshot identifiers and content hashes.

## CLI

The `vr` CLI (`cli/`) is a TypeScript tool that bridges CI and the backend. It's deliberately capture-agnostic: it works with any tool that produces PNGs (Storybook, Playwright, Cypress, etc.).

Snapshot ID is derived from the PNG filename: `button--primary.png` → `button--primary`. Explicit and predictable.

The CLI uploads directly to S3 via presigned POST URLs — the backend never proxies image bytes. Log output goes to stderr so stdout stays clean for machine-readable output (e.g. run IDs for CI capture).

### Commands

**`vr submit`** — single-command flow. Scans a directory, hashes PNGs, creates a run with full manifest, uploads, and completes. Default `--purpose review` (gating, exits 1 on unapproved changes). Pass `--purpose observe` on master/non-PR runs for tracking-only (no approval prompt). An observe run still exits 1 on snapshot drift, so pass `--tolerate-drift` too where a red job is not wanted. Pass `--auto-approve` to approve everything and write the signed baseline (forces `--purpose review`).

**`vr verify`** — local baseline check without API. Hashes PNGs in a directory and compares against `snapshots.yml`. No backend involvement.

**`vr run create`** — creates an empty pending run, outputs the run ID to stdout. Call once before shards. Default `--purpose review`; pass `--purpose observe` on master to make the run tracking-only (non-approvable, no PR comment).

**`vr run upload`** — per-shard: hashes PNGs in a directory, sends identifiers + hashes via `add-snapshots`, uploads missing artifacts. Pass `--storybook-index <index.json> --storybook-root <dir>` to send the Storybook build's story-to-file map, which the debt digest and the flakiness page use to find each snapshot's owning team. A map that cannot be read or sent is logged and does not fail the upload.

**`vr run complete`** — triggers completion (classification, removal detection, diffs).
Exits 1 if unapproved changes are detected, 0 if clean or `--auto-approve` is set, and 2 if the command itself failed (auth, network, timeout, backend processing).
Pass the same `--purpose` the run was created with.
On `--purpose observe` the command names the drifted identifiers, emits a `::warning::` annotation, and exits 1.
The CLI has to be the one to say so: the backend reports zero unresolved for an observe run whatever drifted, so a clean run and a drifting one look identical to it.
Add `--tolerate-drift` to report the drift and still exit 0. Use it on the default branch, where there is no merge left to stop and a red job would block the repair too.

### Run purposes

- **`review`** (default) — approvable. Backend posts PR comment prompts; UI surfaces it under "needs review"; CLI gates on unapproved changes.
- **`observe`** — tracking only. Backend rejects approval attempts; no PR comment; excluded from "needs review". The commit status is posted green (`success`, "Tracking only…") to a separate, non-gating `… (tracking)` context — never the gating `PostHog Visual Review / {run_type}` one. `purpose` is client-supplied, so greening the gating context would let an observe run bypass branch protection on a PR head SHA; the separate context keeps observe runs informational-only (like `(partial)` runs). The UI hides all approval affordances. Use on master pushes and merge-queue branches, where there's no PR to approve.
  The commit status never gates, but the exit code of `vr run complete` still does, and that is where a caller chooses. A merge-queue branch renders the tree about to land, so it lets drift fail the job. Master passes `--tolerate-drift` instead.

### PR comments

Enabled per repo with `enable_pr_comments`.
A run that needs review posts its own comment, so GitHub notifies the reviewers and the prompt sits at the bottom of the PR with the new changes.
GitHub sends nothing for an edit, so a run must not rewrite an earlier comment into a new prompt — a reviewer who already approved would never learn that more changes arrived.
After the new prompt lands, the run clears the previous comment of its own run type: an approval is kept and marked as covering an earlier revision, an unanswered prompt is deleted.
This order keeps the existing prompt on the PR when the post fails.
Each run type keeps its own live prompt, because each one has a separate gate and a separate approval.
An approval updates the prompt of its own run in place, because the reviewer who approved needs no notification.
A run that never got a prompt, because it found nothing to review or because the post failed, posts a new comment on approval instead.

## Current state

Working end to end: CI upload → async diff → GitHub Check → web review → approve → baseline commit → clean re-run. Multi-repo per team, snapshot change history across runs, run supersession, GitHub commit status checks on transitions.

**Tolerated hashes** — when the diff classifies a snapshot as below-threshold noise, it caches the `(identifier, baseline_hash, alternate_hash)` tuple.
Future runs skip diffing entirely for cached pairs.
Developers can also manually tolerate a snapshot from the UI.
When a snapshot already has 3 manual or agent tolerations, or 10 automatic ones, in the last 30 days, the Tolerate button offers a quarantine first, because another toleration covers only that one rendering.

**Row alignment** — a panel that grows by a pixel moves everything below it down, which a top-aligned pixel diff reads as a page-wide change.
Before thresholding, the diff pairs the rows that exist in both images, so the classifier sees only what actually changed.
A shift of one or two rows with nothing else changed is absorbed as noise, and the snapshot keeps the shift in `diff_metadata.row_shift` plus a diff image that shows the moved row, so the run leaves a trace instead of disappearing.
A taller shift is `change_kind=layout`, which still needs review.
The cap is measured against the committed baseline on every run, so absorbed shifts cannot accumulate into a page that quietly moved.

**Quarantine** — known-flaky identifiers can be quarantined per repo and run type.
Quarantined snapshots are still captured and diffed but excluded from gating.
A quarantined snapshot reaches the baseline only when a person approves it by identifier, because "Approve all" skips quarantined snapshots.
This is how a quarantined story's entry keeps up with the story.
The story still renders on every run, so a code change to it makes the entry stale while the quarantine hides the drift, and every run fails on the day the quarantine is lifted or expires.
It is also how a story gets an entry when it has none and the quarantine must stay, because every run without the entry classifies the story `new`, and lifting the quarantine first fails every run until the entry lands.
The procedure is: open a PR that renders the story, approve the `changed` or `new` snapshot on that run by identifier (the API or the `visual-review-runs-approve-create` MCP tool), finalize the run so the entry is committed to the PR branch, then merge the PR.
A PR renders only the stories its diff affects, so a story the PR does not touch needs the full matrix: add the `run-ci-frontend` label before the push that should render it.
The label only widens a Storybook run that happens anyway, so the PR must also change a path the Storybook workflow watches.

Lift the quarantine after the merge.
A lift records the default branch's head commit, and a run whose commit does not contain that commit still treats the story as quarantined.
That matters because an entry on the default branch does not reach a branch that forked before it, and healing cannot supply it either: healing reads the merge-base, which for such a branch also predates the entry.
So an older branch keeps the quarantine until it merges the default branch, and the lift cannot red its gate.
The scope lasts `LIFT_SCOPE_DAYS` from the lift, and after that the lift applies to every branch.
A quarantine that expires on its own date records no commit, so its end applies to every branch at once.

**Flakiness tab** — scores each snapshot identity on the share of the last 7 days of default-branch runs that rendered it differently from its baseline.
The share is split in two, because the two cost different things: a `hard` run failed the gate and blocked whoever was merging, and a `soft` run was absorbed by a toleration and blocked nobody.
`hard` counts every result that is not `unchanged`, matching what `gating._is_unresolved` blocks on: a diff over a threshold, a baseline that was never committed or was dropped from the file, and a baseline whose story no longer renders.

Rows are read over 30 days but rated over 7.
The rate has to lapse before the history does, so a quarantine over a snapshot that stopped failing last week becomes liftable while the activity strip still shows what it used to do.

The Team facet narrows the list to the snapshots one team owns.
Each Storybook entry carries `owner_team`, resolved the same way as the debt digest: the newest default-branch run's story index names the story file, and `owners.yaml` names the team that owns it.
`unowned` means no entry covers the file, and a null owner means the file or its owner is unknown, so the row only appears when no team is selected.
The digest's "Open flakiness overview" button links here with `#teams=<team slug>`.

The states are an urgency ladder, and each rung asks for a different fix:

| State      | Meaning                                                        | Fix                                         |
| ---------- | -------------------------------------------------------------- | ------------------------------------------- |
| `broken`   | Fails nearly every run                                         | Correct the baseline; a quarantine hides it |
| `unstable` | Fails some runs and not others                                 | Stabilize the story, or quarantine it       |
| `at_risk`  | Never fails, but its worst absorbed diff is near the threshold | Fix it before it starts failing             |
| `noisy`    | Renders variants, absorbed with room to spare                  | Nothing                                     |
| `clean`    | Nothing failing or absorbed inside the rate span               | Nothing                                     |

The page groups `noisy` and `clean` under one "Quiet" tile, so every listed entry is reachable from some tile.
A row can be listed for history the rate span no longer counts, and it would otherwise sit in the totals with no way to display it.

`at_risk` exists because always being absorbed is not a safety property.
A snapshot passes only while it stays under both diff thresholds, so one absorbed at 0.01% will never cross and one absorbed just under the line is a hard failure waiting for the next unrelated restyle.
`headroom` is what the worst absorbed run leaves free, measured against the pixel threshold: a `tolerated_hash` match copies the diff recorded when the variant was minted, and the image is byte-identical to that mint, so the number is exact rather than a re-measurement.

Open quarantines appear in the same list, with extend and lift on the row.
`needs a decision` flags one that has run out, is about to, or covers a snapshot that stopped failing the gate.
It turns on hard failures rather than on variants: a snapshot only fails the gate when its diff is over a threshold, which is the one case that records no variant at all, so scoring on variants reported every quarantine still doing its job as covering a snapshot that had gone clean.

`variant_count` stays scoped to the current baseline, because a `ToleratedHash` row is stored against a `baseline_hash` and the classifier only matches a row whose hash is still the baseline.
Variants recorded against a superseded baseline can never match again.

**Known gaps:**

- Frontend error toast swallows structured error codes (`sha_mismatch`, `stale_run`) instead of showing tailored messages

**Not yet built:**

- Auto-release of a quarantine whose snapshot has gone clean (the flakiness tab flags it, a human still decides)
- Server-side thumbnailing for the snapshot strip
- Webhook-driven run creation (currently CLI-initiated only)
