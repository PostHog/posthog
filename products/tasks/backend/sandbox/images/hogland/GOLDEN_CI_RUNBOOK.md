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

0. `validate_ref` job — resolves the `workflow_dispatch` `ref` input to a safe
   checkout target before any other job touches it: blank → `master`; a
   non-blank value is confirmed via the compare API to already be an ancestor
   of `master`, otherwise the run fails here instead of checking out unmerged
   code into a job that (once armed) holds hogland/prod credentials. Also gates
   on `github.ref == 'refs/heads/master'` — see "Known open security issues".
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
7. On success, re-points `posthog-tasks-default` at the candidate's snapshot and
   stamps a dated archive alias `posthog-tasks-default-YYYYMMDD` for rollback.

> A `validate_ref` job now resolves and checks the `ref` `workflow_dispatch`
> input before `render_skills` or `bake` touch it — see step 0 above and
> "Known open security issues" near the bottom of this runbook for what is and
> is not covered by that fix.

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
   the OIDC mint succeeds and hogplane returns 401. **Pin `ref: refs/heads/master`
   if hogplane's TrustMapping schema supports it** — see "Known open security
   issues" below; nothing in the workflow file itself restricts dispatch to
   `master` today, so this per-cluster mapping is the only real backstop.
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

- Manual: Actions → "Tasks Golden Snapshot CD" → Run workflow, dispatched from
  `master` (dispatching from any other branch is a no-op — see `validate_ref`
  above). Leave `cluster` blank to bake every armed cluster, or set it to `dev` /
  `prod-us` to bake one. Leave `ref` blank to render the skills from `master`, or
  set it to a branch or SHA the `validate_ref` job confirms is already an
  ancestor of `master` — an unmerged branch tip is rejected before checkout.
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
- **The golden tracks the render ref (default this workflow's checkout ref).**
  The `render_skills` job checks out PostHog at that ref and renders the skills
  from it, and `setup-golden.sh` reconstructs `Dockerfile.sandbox-base` from the
  same checkout — so the ref is the one knob for what the golden tracks. On the
  nightly schedule this is `master`; pass the `ref` `workflow_dispatch` input to
  bake from a specific branch or SHA for a reproducible golden. `@posthog/agent`
  is decoupled from the ref: the workflow resolves the latest published version
  and pins it into the bake, so the golden's agent-server is reproducible without
  depending on any image.

## Known open security issues

One of the two issues raised in PR review is now fixed in the workflow YAML;
the other needs an out-of-repo change (a hogplane TrustMapping field) that
no edit to this file can substitute for.

- **`ref` workflow_dispatch input checked out with no validation — fixed.**
  `render_skills` and `bake` used to do
  `ref: ${{ github.event.inputs.ref || github.sha }}` directly, so any
  collaborator who can `workflow_dispatch` this workflow could point `ref` at
  a branch carrying a modified `bake-golden.sh`/`setup-golden.sh`/skills build
  and have it run in a job that (once armed) holds the hogland CLI App private
  key, a tailnet join, and hogland/prod OIDC. Fixed by the `validate_ref` job:
  blank `ref` resolves to `master`; a non-blank value must be confirmed, via
  the GitHub compare API, to already be an ancestor of `master`, or the run
  fails before either checkout happens. `render_skills` and `bake` now check
  out `needs.validate_ref.outputs.ref`, never the raw input.
- **Branch dispatch bypasses deployment review — partially mitigated, needs a
  hogplane-side fix to fully close.** Because GitHub runs whatever copy of
  this workflow lives on the ref you dispatch it from, and includes that ref
  in the OIDC token's claims, a collaborator can push a branch with a modified
  copy of this workflow (e.g. with the arming-variable gate or the
  `validate_ref` job itself removed) and dispatch it from that branch. Every
  job in this file now requires `github.ref == 'refs/heads/master'`
  (`validate_ref`'s `if`, transitively gating `render_skills`/`bake` through
  `needs.validate_ref.result == 'success'`), which stops dispatching from a
  branch _as this file's `master` copy defines it_ — but a branch copy that
  deletes that check can still run its own logic and mint a token, because
  hogplane's `github_oidc` TrustMapping (as documented) only checks
  `(repo, workflow)`, not `ref`. The only fix that cannot be bypassed by
  editing the workflow file is pinning `ref: refs/heads/master` in that
  TrustMapping for every cluster (see "Per-cluster prerequisites" above); the
  in-file gate here is defense-in-depth, not a substitute for it.
