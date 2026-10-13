# Tasks golden snapshot CI — ops runbook

The workflow `.github/workflows/cd-tasks-golden-snapshot.yml` bakes the task
sandbox golden snapshot and promotes the alias `posthog-tasks-default` that
`HoglandSandbox.create`
(`products/tasks/backend/logic/services/hogland_sandbox.py`) restores every task
box from.

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
   `cd-sandbox-base-image.yml`'s `build_skills` job does. It stands up a DB,
   restores the schema cache saved on master so `migrate` only tops up the newer
   migrations, runs `setup_dev --no-data`, then `hogli build:skills` to expand the
   skill `.md.j2` templates and merges in the context-mill skills. The DB is
   needed because 24 skill templates call `render_hogql_example`, which reads
   `Team.objects.first()`. Uploads the merged set as the `tasks-golden-skills`
   artifact. Rendered once, reused by every cluster. It shares the master arm
   gate, so an unarmed nightly renders nothing.
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

Before the bake step, a quiet-deploy-window guard waits for no queued or
in-progress hogd rollout and >=900s since the last one (up to 30 min), mirroring
hogland's `golden-snapshots.yml`. The rollout workflow is per cluster (see "Repo
config").

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
   once hogplane's TrustMapping schema supports it** (PostHog/hogland#414, durable
   fix PostHog/hogland#424) — this is the durable fix for the branch-dispatch
   class of attack. The workflow's own
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
   `hogbox-preview-env.yml` already uses. One join reaches the `tag:hogplane`
   device serving each cluster's API, so if preview is already provisioned no
   extra tailnet onboarding is needed for the API calls.
5. **Tailnet route to the box VPC (required for `--access-type ssh-private`).**
   The bake and smoke reach the seed/smoke box over its VPC IP, not the public
   internet. `tag:hogland-ci` reaches `tag:hogplane` today, but **not** a box's
   VPC IP — so `ssh-private` fails at the first `ssh` until a grant is added in
   `posthog-cloud-infra/tailnet-policy.hujson`:

   ```text
   src: tag:hogland-ci
   dst: 10.90.0.0/16:10000-59999, 10.91.0.0/16:10000-59999
   ```

   This is an ops/infra prerequisite (like the svc-ci principal and arming), not
   a repo change. Do not arm any cluster before it lands, or every bake fails on
   the SSH reachability wait.

## Repo config (PostHog/posthog)

- **Variables** (Settings → Secrets and variables → Actions → Variables):
  - `HOG_TASKS_GOLDEN_ENABLED=true` — master arm. Until set, the whole job is a
    no-op. Set it once the dev prerequisites (steps 1–5, including the tailnet route to the box VPC) exist.
  - `HOG_TASKS_GOLDEN_PROD_ENABLED=true` — second arm for prod-targeting
    clusters. The prod-us leg stays a no-op until this is set, so it does not
    fail nightly before its own principal + TrustMapping exist.
  - No `HOGLAND_CLI_REF` needed — the workflow resolves the newest released
    `vX.Y.Z-cli` tag from `PostHog/hogland` at runtime (immutable and reviewed,
    never `main`), guarding a `v1.5.0-cli` minimum.
  - The quiet-window guard's rollout workflow is **per cluster**, hardcoded in the
    bake matrix (dev: `deploy.yml`, prod-us: `promote-to-prod.yml`) — not a shared
    var, because the two clusters roll out through different workflows. The guard
    counts `queued` + `in_progress` runs and waits up to 30 min for a quiet window.
    It reads `PostHog/hogland` Actions with the hogland App token, so that App
    installation needs `actions:read` on hogland; without it the guard fails open
    (a racing rollout only wastes a run, it cannot corrupt the alias). Adding a
    cluster means adding its rollout workflow file to the matrix.
  - `TS_HOGLAND_CI_CLIENT_ID`, `TS_HOGLAND_CI_AUDIENCE` — shared with
    `hogbox-preview-env.yml`; already present if preview is provisioned.
- **Secrets** — the workflow checks out `PostHog/hogland` to build the CLI with
  the existing `GH_APP_HOGLAND_DEPLOYER` GitHub App (org secrets
  `GH_APP_HOGLAND_DEPLOYER_APP_ID` + `GH_APP_HOGLAND_DEPLOYER_PRIVATE_KEY`),
  minted read-only: `contents: read` for the checkout, `actions: read` so the
  quiet-window guard can list hogland rollout runs. The App must be installed on
  `PostHog/hogland` with both.

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

## Cleaning up leaked seed/smoke boxes

The seed (`golden-seed-tasks`) and smoke (`golden-smoke-tasks`) boxes use an
unregistered kind with no server-side TTL, so hogland never reaps them. The
workflow's `always()` teardown deletes them on a normal cancel or failure — but
it does **not** run if the runner itself dies (an infra kill, a spot reclaim),
which leaks a 64 GiB box. The names are fixed, so a leak is at most one seed +
one smoke per cluster (the next run pre-cleans them). After any run that ended
abnormally, sweep them (dev/prod-us need the tailnet):

```bash
for n in golden-seed-tasks golden-smoke-tasks; do
  id=$(hogland box list | jq -r --arg n "$n" 'map(select(.spec.name==$n)) | .[0].id // empty')
  [ -n "$id" ] && hogland box delete "$id"
done
```

## Rollback

Each successful bake stamps `posthog-tasks-default-YYYYMMDD`. To roll back, point
the live alias at a known-good archive:

```bash
hogland snapshot resolve posthog-tasks-default-<YYYYMMDD> | jq -r .snapshot_id
hogland snapshot alias <snapshot_id> posthog-tasks-default
```

After hogland#426 the alias PUT is owner-scoped: only the alias's owner (the
`svc-ci-*` principal that first promoted it) or an admin may repoint
`posthog-tasks-default`, so a hand rollback runs as an admin or as svc-ci. See
hogland's `docs/BUILD_TEST_DEPLOY.md` "Alias ownership" section for the adoption
and recovery model.

## Adding prod-eu

1. Provision the prerequisites above in the prod-eu cluster: a
   `svc-ci-tasks-golden` principal, a `github_oidc` TrustMapping
   `{repo: PostHog/posthog, workflow: cd-tasks-golden-snapshot.yml}` (pin
   `ref: refs/heads/master` once PostHog/hogland#414 lands), and the audience
   `hogland.prod-eu.posthog.dev`.
2. Append a matrix entry in the workflow (host + audience + the EU rollout
   workflow file) and confirm the prod arming gate covers it.
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
  assertion **fails open** only on `000` (genuinely unreachable). A `404` (missing
  box or non-owner) is now a hard fail, since it would be a real regression. Once
  PostHog/hogland#416 lands a `box exec`/`box cp` verb (durable fix
  PostHog/hogland#425) and the exec contract is confirmed, make the exec assertion
  a hard gate on all codes.
- **Quiet-deploy-window guard is provisional.** The guard polls `PostHog/hogland`
  Actions for the per-cluster rollout workflow's queued + in-progress runs and
  waits up to 30 min for a quiet window, but **fails open** when the hogland App
  lacks `actions:read` on hogland. Grant the App `actions:read` to arm it. A racing
  rollout without the guard only wastes a run (it orphans the seed box and skips
  promotion), it cannot corrupt the alias.
- **The golden tracks the render ref (default `master`).** The `render_skills` job
  checks out PostHog at the validated ref and renders the skills from it, and
  `setup-golden.sh` reconstructs `Dockerfile.sandbox-base` from the same checkout —
  so the ref is the one knob for what the golden tracks. On the nightly schedule
  this is `master`; pass the `ref` `workflow_dispatch` input (a merged SHA) for a
  reproducible golden. `@posthog/agent` is decoupled from the ref: the workflow
  resolves the latest published version and pins it into the bake.
- **Cluster confirm catches a lost write, not a wrong-cluster bake.** The promote
  step re-resolves `posthog-tasks-default` after the PUT, but on the same
  per-cluster `HOG_HOST` it wrote to. That catches a lost or overwritten alias
  write on this cluster; it does not prove the bake targeted the intended cluster.
  A cheap cluster-identity query on the CLI would let it assert the expected
  cluster name — not available today, so this stays a lost-write check.
- **The `tasks-golden-skills` artifact is public-downloadable.** It is a
  build artifact on a public repo, so anyone can download it. Its content is
  repo-derived (rendered skills + fixtures) — confirm the render emits nothing
  beyond repo fixtures before treating the golden as sensitive-free.
- **Unpinned third-party installs.** `setup-golden.sh` runs the nodesource
  `setup_24.x` piped to `bash`, the gh `.deb` with no sha256, and global npm
  tools — the same posture as `Dockerfile.sandbox-base`. The nightly rebake
  widens the window in which an upstream change lands in a golden unnoticed.
- **hogland#410 (per-box `PATH`) forces a full rebake.** When it lands it requires
  a rebake of every golden, and its per-box `PATH` overrides this drop-in.

## Known open security issues

The `ref` RCE and branch-dispatch findings from PR review are now **mitigated in
`cd-tasks-golden-snapshot.yml`**: the unprivileged `validate_ref` job resolves and
ancestor-checks the `ref` input before any credentialed checkout, and every
privileged job gates on `github.ref == 'refs/heads/master'`. The residual, durable
gap is hogland-owned:

- **Branch dispatch — durable fix is hogland-side (PostHog/hogland#414, durable
  fix PostHog/hogland#424).** The in-file `github.ref == 'refs/heads/master'` gates
  raise the bar, but a branch copy of the workflow can strip them. The fix that
  cannot be bypassed from the repo is pinning `ref: refs/heads/master` in each
  cluster's `github_oidc` TrustMapping. Until #414 lands and the mapping is pinned,
  treat the in-workflow gates as the only barrier and keep dispatch discipline
  (dispatch only from `master`).
- **Alias namespace is global and unprotected (PostHog/hogland#415, durable fix
  PostHog/hogland#426).** Alias PUT checks only new-snapshot ownership and DELETE
  checks nothing, so a `svc-ci-tasks-golden` principal on prod-us could repoint or
  delete `devbox-golden` / `posthog-preview-golden`. **Keep prod-us UNARMED
  (`HOG_TASKS_GOLDEN_PROD_ENABLED` unset) until #415 lands.** Arming dev grants the
  CI principal delete over `devbox-golden` (which lives on dev), so dev is only
  acceptable to arm knowingly — #426 mitigates this once it lands.

## hogland dependencies (filed issues)

Items owned by the hogland team, filed from this review. Not blockers for merging
the workflow (it is a no-op until armed), but referenced above:

- **PostHog/hogland#414** — `github_oidc` TrustMapping cannot pin a `ref` (durable
  branch-dispatch fix, PR PostHog/hogland#424). Gates arming prod-us safely.
- **PostHog/hogland#415** — alias namespace PUT/DELETE unprotected (durable fix PR
  PostHog/hogland#426). With #426 merged, `svc-ci` adopts `posthog-tasks-default`
  on its first PUT (a new alias is owned by its creator), so no extra
  provisioning step — see hogland `docs/BUILD_TEST_DEPLOY.md` (Alias ownership).
- **PostHog/hogland#416** — no `box exec` / `box cp` verb: `hogland box exec` does
  not exist today, so the smoke uses a raw `POST .../exec` (durable fix PR
  PostHog/hogland#425). Also covers the batch `/exec` timeout mismatch (advertises
  6h, caps at 60s).
- **PostHog/hogland#417** — snapshot chunks are never GC'd (a daily bake leaks
  ~10-25 GiB). Must be reference-aware, **not** a bucket-wide expiry rule (that
  caused the 2026-08-06 preview outage).
- **PostHog/hogland#418** — hogbox env / `EnvironmentFile` ordering: an
  `EnvironmentFile=` key can override the guard-critical `Environment=` vars, so
  the drop-in sets no `EnvironmentFile`.
