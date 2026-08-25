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

1. Joins the hogland tailnet as `tag:hogland-ci` (the tag whose ACL reaches the
   `tag:hogplane` device serving the API).
2. Authenticates to hogplane as a per-cluster `svc-ci-*` service-account
   principal via GitHub OIDC — no stored bearer. The CLI mints the token from the
   Actions OIDC endpoint and re-mints on any mid-bake 401 via `HOG_TOKEN_COMMAND`,
   because a golden bake runs ~90 min while an OIDC token lives ~5 min.
3. Builds the `hogland` CLI from a scoped checkout of `PostHog/hogland`.
4. `hogland snapshot-build --alias posthog-tasks-candidate --setup-script
setup-golden.sh` — builds a seed box, runs the setup script inside it,
   snapshots it, and points the candidate alias at the snapshot.
5. Boots a smoke box from `posthog-tasks-candidate`, runs `smoke-golden.sh`
   (agent-server starts; a trivial clone + exec works), and deletes it. A smoke
   failure skips promotion, leaving `posthog-tasks-default` on the previous
   known-good snapshot.
6. On success, re-points `posthog-tasks-default` at the candidate's snapshot and
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
   `{repo: PostHog/posthog, workflow: cd-tasks-golden-snapshot.yml}` →
   `svc-ci-tasks-golden`. TrustMappings are per-cluster runtime data — the dev
   mapping grants nothing in prod-us, so create it again per cluster. Without it
   the OIDC mint succeeds and hogplane returns 401.
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
- Nightly: the `schedule` cron fires daily but only bakes armed clusters.

## Rollback

Each successful bake stamps `posthog-tasks-default-YYYYMMDD`. To roll back, point
the live alias at a known-good archive:

```
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
- **Exec-daemon env restart is deferred.** `setup-golden.sh` lays down the
  agent-daemon systemd env drop-in and reloads the unit, but does not restart the
  daemon in-bootstrap (a restart would kill the bootstrap script before the
  success marker). Confirm exec processes see the container-style env (PATH with
  `/opt/posthog/bin` first, `IS_SANDBOX=1`, ...) after a real restore; if not, the
  drop-in needs a restart wired the way the terminal bake detaches it.
- **No quiet-deploy-window guard.** hogland's own golden workflow waits for a
  quiet hogd rollout window; this workflow does not (that needs cross-repo API
  access to hogland's deploy runs). A hogd rollout racing the bake orphans the
  seed box, which just times out `snapshot-build` and skips promotion — safe, but
  a wasted run. Consider adding the guard in a later phase.
- **The golden tracks `master` + `@posthog/agent@latest`.** `setup-golden.sh`
  clones `master` and installs the latest published agent, like the preview
  persona. Pin `POSTHOG_REF` / `POSTHOG_AGENT_VERSION` (both read from the
  environment) if a bake must be reproducible to an exact commit.
