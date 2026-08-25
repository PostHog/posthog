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

1. `validate_ref` job — resolves the `workflow_dispatch` `ref` input to a safe
   checkout target before any other job touches it: blank resolves to the
   literal `master` branch, and a non-blank value must be a full commit SHA that
   GitHub's compare API confirms is already an ancestor of `master`. This job
   never checks out any code itself (only a REST call), because `render_skills`
   and `bake` both check out their ref and then execute scripts from it
   (`hogli build:skills`, `bake-golden.sh`, `setup-golden.sh`) in jobs that, once
   armed, hold the hogland CLI App key, a tailnet join, and hogland/prod OIDC —
   an unvalidated free-text ref would let anyone who can dispatch this workflow
   run their own branch's code with those credentials.
2. `render_skills` job — renders the agent skills the golden ships, the same way
   the sandbox-base image build does (`cd-sandbox-base-image.yml`'s `build_skills`
   job): stands up a DB, `uv sync`s, migrates, runs `hogli build:skills` to expand
   the skill `.md.j2` templates, then merges in the context-mill skills. Uploads
   the merged set as the `tasks-golden-skills` artifact. Rendered once, reused by
   every cluster. It shares the master arm gate, so an unarmed nightly does not
   pay for a full DB render.
3. Joins the hogland tailnet as `tag:hogland-ci` (the tag whose ACL reaches the
   `tag:hogplane` device serving the API).
4. Authenticates to hogplane as a per-cluster `svc-ci-*` service-account
   principal via GitHub OIDC — no stored bearer. The CLI mints the token from the
   Actions OIDC endpoint and re-mints on any mid-bake 401 via `HOG_TOKEN_COMMAND`,
   because a golden bake runs ~90 min while an OIDC token lives ~5 min.
5. Builds the `hogland` CLI from a scoped checkout of `PostHog/hogland`.
6. `bake-golden.sh` — decomposes the bake into box primitives instead of
   `hogland snapshot-build` (whose <=256 KiB bootstrap cannot carry the multi-MB
   skills set). It `box create`s a bare seed box (cold boot, `--no-connect`),
   streams the payload into the box over the box's own SSH (`cat >` — the git/gh
   guards, the cpu sampler, the rendered-skills tarball, `install-skills.sh`, and
   `setup-golden.sh`), runs `setup-golden.sh` in the box, then `box snapshot`s the
   result and points the candidate alias at it. `setup-golden.sh` installs
   node/uv/tools/agentsh fresh, npm-installs `@posthog/agent` at the version the
   workflow resolved, and installs the delivered skills. No GHCR image and no
   public artifact host are involved — delivery rides the box's SSH.
7. Boots a smoke box from `posthog-tasks-candidate`, runs `smoke-golden.sh`
   (agent-server starts; a trivial clone + exec works; the hogpanion exec daemon
   is running with the container-style env), and deletes it. A smoke failure
   skips promotion, leaving `posthog-tasks-default` on the previous known-good
   snapshot.
8. On success, re-points `posthog-tasks-default` at the candidate's snapshot and
   stamps a dated archive alias `posthog-tasks-default-YYYYMMDD` for rollback.

The matrix covers **dev** and **prod-us**. **prod-eu is deferred** to the EU
rollout — see "Adding prod-eu" below.

## Per-cluster prerequisites (hogland team, out-of-band)

These are hogland runtime-cluster data, not repo config. They mirror the
`preview` persona's provisioning in hogland's `docs/BUILD_TEST_DEPLOY.md`.

For **each** cluster the workflow targets (dev, then prod-us):

1. **Service-account principal.** Create a `svc-ci-tasks-golden` principal via
   `POST /v1/service-accounts` on that cluster's hogplane.
2. **`github_oidc` TrustMapping.** Map this repo's workflow to that principal:
   `{repo: PostHog/posthog, workflow: cd-tasks-golden-snapshot.yml, ref: refs/heads/master}` →
   `svc-ci-tasks-golden`. TrustMappings are per-cluster runtime data — the dev
   mapping grants nothing in prod-us, so create it again per cluster. Without it
   the OIDC mint succeeds and hogplane returns 401. **Pin `ref: refs/heads/master`
   if hogplane's TrustMapping schema supports it.** Every job in this workflow
   now also requires `github.ref == 'refs/heads/master'` before it will run, but
   that check lives in the workflow file, so a branch that carries a modified
   copy of the workflow could remove it and still dispatch under this repo's
   OIDC claims. Only a ref-pinned TrustMapping on hogplane's side closes that gap
   for real — the in-workflow check is defense in depth, not the fix.
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
  - `HOGLAND_CLI_REF` (optional) — the `PostHog/hogland` ref to build the CLI
    from. Defaults to `main`.
  - `TS_HOGLAND_CI_CLIENT_ID`, `TS_HOGLAND_CI_AUDIENCE` — shared with
    `hogbox-preview-env.yml`; already present if preview is provisioned.
- **Secrets** — a GitHub App with read access to `PostHog/hogland` (for the CLI
  checkout), exposed as `GH_APP_HOGLAND_CLI_APP_ID` +
  `GH_APP_HOGLAND_CLI_PRIVATE_KEY`. See `/managing-github-actions-secrets`.

## Running it

- Manual: Actions → "Tasks Golden Snapshot CD" → Run workflow. Leave `cluster`
  blank to bake every armed cluster, or set it to `dev` / `prod-us` to bake one.
  Leave `ref` blank to render the skills from `master`, or set it to a full
  commit SHA already merged into `master` to bake a reproducible golden from
  that commit — `validate_ref` rejects anything else (see below).
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
   `{repo: PostHog/posthog, workflow: cd-tasks-golden-snapshot.yml}`, and the
   audience `hogland.prod-eu.posthog.dev`.
2. Append a matrix entry in the workflow (host + audience) and confirm the prod
   arming gate covers it.
3. Confirm `tag:hogland-ci` reaches the prod-eu `tag:hogplane` device.

## Known Phase-1 gaps (validate on a live cluster)

- **No live bake has run.** The scripts and workflow are lint- and
  shellcheck-clean, but a real bake needs a cluster, the tailnet, and the
  principal — none of which exist in local dev. First armed run is the real test.
- **Smoke asserts the daemon env, not a real hog-exec child.** `smoke-golden.sh`
  reads the running hogpanion daemon's live `/proc/<MainPID>/environ` — the env
  its hog-exec children inherit — and asserts `IS_SANDBOX=1`, a `/opt/posthog/bin`
  first `PATH`, and `PYTHONPATH`. This catches a hogpanion that never re-exec'd
  with the drop-in, which an SSH login shell would hide (PAM feeds it
  `/etc/environment`). It does not yet spawn a command _through_ hogpanion's exec
  API and assert on the child directly. Wiring that (via `hogland box exec` or the
  in-box exec endpoint) is the intended upgrade once the CLI surface is confirmed.
  The daemon-env assert also depends on the sandbox ssh user being root (it reads
  another process's `/proc` environ); the task sandbox runs as root.
- **No quiet-deploy-window guard.** hogland's own golden workflow waits for a
  quiet hogd rollout window; this workflow does not (that needs cross-repo API
  access to hogland's deploy runs). A hogd rollout racing the bake orphans the
  seed box, which fails the in-box SSH steps and skips promotion — safe, but a
  wasted run. Consider adding the guard in a later phase.
- **The golden tracks the render ref (default `master`).** The `render_skills`
  job checks out PostHog at the ref `validate_ref` resolved, and renders the
  skills from it; `setup-golden.sh` reconstructs `Dockerfile.sandbox-base` from
  the same checkout — so the ref is the one knob for what the golden tracks. It
  defaults to `master`; pass the `ref` `workflow_dispatch` input (a full commit
  SHA already merged into `master`) to bake from a specific commit for a
  reproducible golden. `@posthog/agent` is decoupled from the ref: the workflow
  resolves the latest published version and pins it into the bake, so the
  golden's agent-server is reproducible without depending on any image.
- **`ref` must already be merged into `master`.** `validate_ref` checks any
  non-blank `ref` input against GitHub's compare API before `render_skills` or
  `bake` ever checks it out, because both jobs execute scripts from that
  checkout with hogland/prod credentials once armed. An unmerged commit (e.g.
  from an open PR) fails validation and the whole run stops before touching
  hogland.
