# Tasks golden snapshot CI — ops runbook

The workflow `.github/workflows/cd-tasks-golden-snapshot.yml` bakes the task
sandbox golden snapshot and promotes the alias `posthog-tasks-default` that
`HoglandSandbox.create` restores every task box from. It replaces the terminal
bake in `products/tasks/management/commands/bake_hogland_snapshot.py` once the
CI path is proven.

This runbook covers the hogland-team dependencies each cluster needs **before**
the workflow can run. Until they exist and the arming variables are set, the
workflow is a deliberate no-op (the job `if` gates on `HOG_TASKS_GOLDEN_ENABLED`)
so a merged-but-unprovisioned workflow never sits red.

Modal / `Dockerfile.sandbox-base` is untouched by this workflow — it bakes the
same contents into a hogland snapshot, it does not change the container image.

## What the workflow does

0. `validate_ref` job (unprivileged, no secrets) — resolves the
   `workflow_dispatch` `ref` input before any credentialed job checks that tree
   out. Blank resolves to the literal `master` branch; a non-blank value must be
   a full 40-char commit SHA that the GitHub compare API confirms is already an
   ancestor of `master`, else the job fails. `render_skills` and `bake` check out
   `needs.validate_ref.outputs.ref`, never the raw input, and every privileged
   job additionally gates on `github.ref == 'refs/heads/master'`. This closes the
   `ref` RCE in the workflow YAML (see "Known open security issues").
1. `render_skills` job — renders the agent skills the golden ships, the same way
   the sandbox-base image build does (`cd-sandbox-base-image.yml`'s `build_skills`
   job): stands up a DB, `uv sync`s, migrates, runs `hogli build:skills` to expand
   the skill `.md.j2` templates, then merges in the context-mill skills. Uploads
   the merged set as the `tasks-golden-skills` artifact. Rendered once, reused by
   every cluster. It shares the master arm gate, so an unarmed nightly does not
   pay for a full DB render.
2. Joins the hogland tailnet as `tag:hogland-ci` (the tag whose ACL reaches the
   `tag:hogplane` device serving the API).
3. Authenticates to hogplane as a per-cluster `svc-ci-*` service-account
   principal via GitHub OIDC — no stored bearer. The CLI mints the token from the
   Actions OIDC endpoint and re-mints on any mid-bake 401 via `HOG_TOKEN_COMMAND`,
   because a golden bake runs ~90 min while an OIDC token lives ~5 min.
4. Builds the `hogland` CLI from a scoped checkout of `PostHog/hogland`.
5. `bake-golden.sh` — decomposes the bake into box primitives instead of
   `hogland snapshot-build` (whose <=256 KiB bootstrap cannot carry the multi-MB
   skills set). It `box create`s a bare seed box (cold boot, `--no-connect`),
   streams the payload into the box over the box's own SSH (`cat >` — the git/gh
   guards, the cpu sampler, the rendered-skills tarball, `install-skills.sh`, and
   `setup-golden.sh`), runs `setup-golden.sh` in the box, then `box snapshot`s the
   result and points the candidate alias at it. `setup-golden.sh` installs
   node/uv/tools/agentsh fresh, npm-installs `@posthog/agent` at the version the
   workflow resolved, and installs the delivered skills. No GHCR image and no
   public artifact host are involved — delivery rides the box's SSH.
6. Boots a smoke box from `posthog-tasks-candidate`, runs `smoke-golden.sh`
   (agent-server starts; a trivial clone + exec works; the hogpanion exec daemon
   is running with the container-style env), and deletes it. A smoke failure
   skips promotion, leaving `posthog-tasks-default` on the previous known-good
   snapshot.
7. On success, re-points `posthog-tasks-default` at the candidate's snapshot
   (retrying the alias PUT, since a concurrent repoint returns 500 not 409),
   confirms the live alias resolves to that snapshot in the expected cluster, and
   stamps a dated archive alias `posthog-tasks-default-YYYYMMDD` for rollback.

Before the bake step, a quiet-deploy-window guard waits for no in-progress hogd
rollout and >=900s since the last one, mirroring hogland's `golden-snapshots.yml`
(see "Repo config" for `HOGLAND_ROLLOUT_WORKFLOW`).

The matrix covers **dev** and **prod-us**. **prod-eu is deferred** to the EU
rollout — see "Adding prod-eu" below.

## Per-cluster prerequisites (hogland team, out-of-band)

These are hogland runtime-cluster data, not repo config. They mirror the
`preview` persona's provisioning in hogland's `docs/BUILD_TEST_DEPLOY.md`.

For **each** cluster the workflow targets (dev, then prod-us):

1. **Service-account principal.** Create a `svc-ci-tasks-golden` principal via
   `POST /v1/service-accounts` on that cluster's hogplane. This endpoint is
   admin-only and has no CLI; it mints a name of the form `svc-<slug>-<rand>`, so
   the random suffix is expected — do **not** read it as a failure.
2. **`github_oidc` TrustMapping.** Map this repo's workflow to that principal:
   `{repo: PostHog/posthog, workflow: cd-tasks-golden-snapshot.yml}` →
   `svc-ci-tasks-golden`. TrustMappings are per-cluster runtime data — the dev
   mapping grants nothing in prod-us, so create it again per cluster. Without it
   the OIDC mint succeeds and hogplane returns 401. **Pin `ref: refs/heads/master`
   once hogplane's TrustMapping schema supports it** (PostHog/hogland#419) — this
   is the durable fix for the branch-dispatch class of attack. The workflow's own
   `validate_ref` job + per-job `github.ref == 'refs/heads/master'` gates raise
   the bar, but a branch copy of the workflow can strip in-file gates, so the
   TrustMapping ref pin is the backstop that cannot be bypassed from the repo.
3. **OIDC audience.** The mint audience is the per-cluster literal in the
   workflow's matrix, kept equal to `hogplane.githubOIDCAudience` in that
   cluster's values file:

   | Cluster | `HOG_HOST`                                    | Audience (`HOG_OIDC_AUDIENCE`) |
   | ------- | --------------------------------------------- | ------------------------------ |
   | dev     | `https://hogland-dev.hedgehog-kitefin.ts.net` | `hogland.dev.posthog.dev`      |
   | prod-us | `https://hogland.hedgehog-kitefin.ts.net`     | `hogland.prod-us.posthog.dev`  |

4. **Tailnet admittance.** The workflow joins as `tag:hogland-ci`, reusing the
   `TS_HOGLAND_CI_CLIENT_ID` + `TS_HOGLAND_CI_AUDIENCE` repo variables that
   `hogbox-preview-env.yml` already uses. One join reaches dev and prod-us, so if
   preview is already provisioned no extra tailnet onboarding is needed.

## Repo config (PostHog/posthog)

- **Variables** (Settings → Secrets and variables → Actions → Variables):
  - `HOG_TASKS_GOLDEN_ENABLED=true` — master arm. Until set, the whole job is a
    no-op. Set it once the dev prerequisites (steps 1–4) exist.
  - `HOG_TASKS_GOLDEN_PROD_ENABLED=true` — second arm for prod-targeting
    clusters. The prod-us leg stays a no-op until this is set, so it does not
    fail nightly before its own principal + TrustMapping exist.
  - `HOGLAND_CLI_REF` (**required**) — the `PostHog/hogland` ref to build the CLI
    from. Must be a released `v*-cli` tag; the workflow fails if it is unset or
    not a `*-cli` tag (a moving branch like `main` is not reproducible).
  - `HOGLAND_ROLLOUT_WORKFLOW` (optional) — the hogd rollout workflow file name in
    `PostHog/hogland` (e.g. `rollout.yml`) that the quiet-window guard polls. Unset
    skips the guard. The guard reads `PostHog/hogland` Actions with the hogland App
    token, so that App installation needs `actions:read` on hogland; without it the
    guard fails open (a racing rollout only wastes a run, it cannot corrupt the
    alias).
  - `TS_HOGLAND_CI_CLIENT_ID`, `TS_HOGLAND_CI_AUDIENCE` — shared with
    `hogbox-preview-env.yml`; already present if preview is provisioned.
- **Secrets** — a GitHub App with read access to `PostHog/hogland` (for the CLI
  checkout), exposed as `GH_APP_HOGLAND_CLI_APP_ID` +
  `GH_APP_HOGLAND_CLI_PRIVATE_KEY`. See `/managing-github-actions-secrets`.

## Running it

- Manual: Actions → "Tasks Golden Snapshot CD" → Run workflow. Leave `cluster`
  blank to bake every armed cluster, or set it to `dev` / `prod-us` to bake one.
  Leave `ref` blank to render from `master`, or set it to a full commit SHA that
  is already merged into `master`. `validate_ref` enforces this: a blank ref
  resolves to `master`, a non-blank value must be a full 40-char SHA that is an
  ancestor of `master`, and anything else (a branch name, an unmerged SHA) fails
  the run before any credentialed job starts. Dispatch only works from `master`
  (every privileged job gates on `github.ref == 'refs/heads/master'`).
- Nightly: the `schedule` cron fires daily but only bakes armed clusters,
  rendering from `master`.

## Rollback

Each successful bake stamps `posthog-tasks-default-YYYYMMDD`. To roll back, point
the live alias at a known-good archive:

```bash
hogland snapshot resolve posthog-tasks-default-<YYYYMMDD> | jq -r .snapshot_id
hogland snapshot alias <snapshot_id> posthog-tasks-default
```

## Adding prod-eu

1. Provision the prerequisites above in the prod-eu cluster: a
   `svc-ci-tasks-golden` principal, a `github_oidc` TrustMapping
   `{repo: PostHog/posthog, workflow: cd-tasks-golden-snapshot.yml}` (pin
   `ref: refs/heads/master` once PostHog/hogland#419 lands), and the audience
   `hogland.prod-eu.posthog.dev`.
2. Append a matrix entry in the workflow (host + audience) and confirm the prod
   arming gate covers it.
3. Confirm `tag:hogland-ci` reaches the prod-eu `tag:hogplane` device.

## Known Phase-1 gaps (validate on a live cluster)

- **No live bake has run.** The scripts and workflow are lint- and
  shellcheck-clean, but a real bake needs a cluster, the tailnet, and the
  principal — none of which exist in local dev. First armed run is the real test.
- **Smoke asserts the daemon env, and best-effort the exec API.** `smoke-golden.sh`
  reads the running hogpanion daemon's live `/proc/<MainPID>/environ` (via `sudo`;
  the box ssh user is `hog`) — the env its hog-exec children inherit — and asserts
  `IS_SANDBOX=1`, a `/opt/posthog/bin` first `PATH`, and `PYTHONPATH`. This catches
  a hogpanion that never re-exec'd with the drop-in, which an SSH login shell would
  hide (PAM feeds it `/etc/environment`). It also now attempts a trivial command
  through `POST /v1/hogboxes/{id}/exec` — the production reach path — but that
  assertion **fails open** on `000/404/501` (the request path may predate the CLI
  surface). Once PostHog/hogland#422 lands a `box exec`/`box cp` verb and the exec
  contract is confirmed, make the exec assertion a hard gate.
- **Quiet-deploy-window guard is provisional.** The guard polls
  `PostHog/hogland` Actions for the `HOGLAND_ROLLOUT_WORKFLOW` runs and waits for a
  quiet window, but **fails open** when the var is unset or the hogland App lacks
  `actions:read` on hogland. Set `HOGLAND_ROLLOUT_WORKFLOW` and grant the App
  `actions:read` to arm it. A racing rollout without the guard only wastes a run
  (it orphans the seed box and skips promotion), it cannot corrupt the alias.
- **The golden tracks the render ref (default `master`).** The `render_skills` job
  checks out PostHog at the validated ref and renders the skills from it, and
  `setup-golden.sh` reconstructs `Dockerfile.sandbox-base` from the same checkout —
  so the ref is the one knob for what the golden tracks. On the nightly schedule
  this is `master`; pass the `ref` `workflow_dispatch` input (a merged SHA) for a
  reproducible golden. `@posthog/agent` is decoupled from the ref: the workflow
  resolves the latest published version and pins it into the bake.

## Known open security issues

The `ref` RCE and branch-dispatch findings from PR review are now **mitigated in
`cd-tasks-golden-snapshot.yml`**: the unprivileged `validate_ref` job resolves and
ancestor-checks the `ref` input before any credentialed checkout, and every
privileged job gates on `github.ref == 'refs/heads/master'`. The residual, durable
gap is hogland-owned:

- **Branch dispatch — durable fix is hogland-side (PostHog/hogland#419).** The
  in-file `github.ref == 'refs/heads/master'` gates raise the bar, but a branch
  copy of the workflow can strip them. The fix that cannot be bypassed from the
  repo is pinning `ref: refs/heads/master` in each cluster's `github_oidc`
  TrustMapping. Until #419 lands and the mapping is pinned, treat the in-workflow
  gates as the only barrier and keep dispatch discipline (dispatch only from
  `master`).
- **Alias namespace is global and unprotected (PostHog/hogland#420).** Alias PUT
  checks only new-snapshot ownership and DELETE checks nothing, so a
  `svc-ci-tasks-golden` principal on prod-us could repoint or delete
  `devbox-golden` / `posthog-preview-golden`. **Keep prod-us UNARMED
  (`HOG_TASKS_GOLDEN_PROD_ENABLED` unset) until #420 lands.** dev is acceptable to
  arm meanwhile.

## hogland dependencies (filed issues)

Items owned by the hogland team, filed from this review. Not blockers for merging
the workflow (it is a no-op until armed), but referenced above:

- **PostHog/hogland#419** — `github_oidc` TrustMapping cannot pin a `ref` (durable
  branch-dispatch fix). Gates arming prod-us safely.
- **PostHog/hogland#420** — alias namespace PUT/DELETE unprotected. Keep prod-us
  unarmed until fixed.
- **PostHog/hogland#421** — batch `/exec` advertises a 6h timeout but caps at 60s.
- **PostHog/hogland#422** — add a `box cp` / files-API delivery (removes SSH+sudo
  from the bake) and a `box exec` verb (`hogland box exec` does not exist today,
  so the smoke uses a raw `POST .../exec` that fails open).
- **PostHog/hogland#423** — snapshot chunks are never GC'd (a daily bake leaks
  ~10-25 GiB). Must be reference-aware, **not** a bucket-wide expiry rule (that
  caused the 2026-08-06 preview outage).
