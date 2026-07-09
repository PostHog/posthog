# hogbox-preview

Per-PR PostHog preview environments, the layer-agnostic way.

Spins PostHog up inside a disposable box and serves it at a **stable URL** that
survives the box being recreated. Today the box is a
[hogland](https://github.com/PostHog/hogland) hogbox (Firecracker microVM,
reachable over the tailnet). It used to be a DigitalOcean droplet
(`bin/hobby-ci.py`), and it may be something else next.

## The one idea: layer vs stack

The thing that changes when we swap providers is small and isolated:

- **Layer** (`backend.py`, `*_backend.py`) — _which box_: how to provision it,
  how to run commands / write files in it, what its URL is, how to destroy it.
  Swapping providers = one new `PreviewBackend`.
- **Stack** (`stack.py`) — _what runs in the box_: the PostHog docker-compose
  recipe (image, override, frontend, migrate, seed, health). It talks to the box
  only through the backend interface and **never changes when the layer changes**.

```python
from hogbox_preview import HoglandBackend, PostHogPreviewStack

backend = HoglandBackend(host="https://hogland.hedgehog-kitefin.ts.net", name="preview-pr-123")
url = PostHogPreviewStack(backend, branch="pull/123/head").bring_up()
print(url)  # https://pen-….boxes.hogland.prod-us.posthog.dev/  (stable across rebuilds)
```

## How it actually works

1. **Restore a warm golden** (`alias:posthog-preview-golden`) — a Firecracker
   snapshot of PostHog already running on the `ghcr.io/posthog/posthog:master`
   image, pg + ClickHouse migrated, demo-data seeded. A warm restore resumes a
   live, serving PostHog in ~30s (no cold boot, no rebuild). Sizing must match
   the golden (8 vCPU / 16 GiB / 100 GiB).
2. **Mount the PR's backend** (`posthog`, `ee`, `products`) over the image's
   `/code` — so the backend runs the PR code with **no per-PR image build**.
3. **Frontend** (only when the PR touches `frontend/**`): the untrusted
   `build-frontend` CI job compiles the PR's `frontend/dist` on the runner **in
   parallel** with the bring-up. Once the box is healthy, the `swap-frontend`
   subcommand ships the dist in (chunked past hogplane's 64 MiB write cap),
   re-runs `collectstatic`, and recreates web — so the box comes up on the
   golden's `:master` SPA first, then swaps to the PR frontend before "ready" is
   posted. Non-FE PRs skip the swap and keep the `:master` SPA. Running the swap
   after bring-up (not inside the single `up`) is what lets the FE build hide
   under the longer bring-up instead of serializing before it.
4. **Delta-migrate** — only the PR's _unapplied_ migrations on top of the seeded
   DB (`--reset-db` if the PR's migrations are incompatible with the baseline).
5. **Serve + report** — the box is HTTP-exposed; the URL is posted to the PR.

Driven entirely by the **`posthog-hogland` Python SDK** over hogplane's HTTP API
— **keyless** (GitHub OIDC → hogplane token over the tailnet), no `hogland` CLI
binary and no box SSH key.

## Pens: the stable URL

The box behind a preview rotates (a fresh restore per push), so the tool keys a
**pen** (hogland's stable identity, `docs/PENS.md` there) on the deterministic
name `preview-pr-<n>`: get-or-create the pen, restore a fresh box, PATCH
`current_box_id`. The posted URL is `https://<pen-id>.<edge>/`, which hogland's
box-http edge resolves to whatever box currently backs the pen — so **a
reviewer's link survives every re-push** (the box swaps underneath). Requires
hogland's pen-id edge routing (shipped in hogland #319).

## Auto-previews & opt-out

Frontend PRs get a preview **automatically** — no label needed. A cheap,
credential-free `decide` job in `hogbox-preview-env.yml` gates every PR event and
builds a preview when **all** hold:

- the PR is **same-repo** (fork PRs never get one — they'd run fork code with the
  hogland token in scope),
- the author is a **human** (bots — `user.type == 'Bot'`, `…[bot]`, and the usual
  suspects like dependabot/renovate — are skipped),
- the PR is **ready** (not draft; flipping draft→ready builds it),
- it does **not** carry the **`no-preview`** opt-out label, and
- it either carries the **`hogbox-preview`** label (manual opt-in, works for **any**
  paths) **or** its diff touches the frontend (`frontend/**`,
  `products/*/frontend/**`, `common/esbuilder/**`).

Two labels, two escape hatches: **`hogbox-preview`** forces a preview on a PR that
wouldn't auto-qualify (e.g. a backend-only change you want to click through);
**`no-preview`** suppresses one on a PR that would (and tears down a live one).

Why a `decide` job and not an `on.pull_request.paths` filter: a path filter would
kill the label-only path for backend PRs, so the trigger stays broad and
eligibility is decided in a job step. Rapid pushes coalesce via a per-PR
`concurrency` group on the build job (cancel-in-progress) — a busy PR (p90 ~17
pushes) rebuilds once for the latest commit, not 17 times. The group is job-level
and keyed on PR number only, so an unrelated label removal can't cancel an active
build.

## Reporting & lifecycle

- **PR comment** — a sticky comment (`<!-- hogbox-preview-comment -->`) staged
  building → ready → failed, with the URL, login, and what's running.
- **GitHub Deployment** — a `preview-pr-<n>` environment (in_progress → success
  /failure + URL), so the preview shows in the PR's Deployments UI.
- **Teardown** — on PR close (`pr-closed.yml`) + on the fast path in
  `hogbox-preview-env.yml`: removing `hogbox-preview` **or** adding `no-preview`
  destroys box + pen. A daily stale-sweep (`cleanup-stale`) in
  `hogbox-preview-cleanup.yml` reaps previews whose PR closed but slipped
  through — its own workflow because the OIDC mint needs `id-token: write`, which
  can't live in the reusable `pr-cleanup.yml`.

## Hibernation & wake (why autos are affordable)

Every preview pen is created with `on_idle=hibernate` + `wake=on-request` (both
re-asserted on each push). After ~30 min idle (the `--ttl-seconds` window),
hogland's reaper **snapshots the box to S3 and deletes it** — zero node cost while
nobody's looking. The **stable URL stays live**: the next visit hits the box-front
edge, which sees a hibernated wake-on-request pen and serves a brief **"waking
up" interstitial** (a polling page for browser navigations, a retry-503 for
XHR/asset clients) while it restores the box (~30–40s, a warm restore of the ready
stack) and repoints the pen. Actively-viewed previews stay awake — edge traffic
touches the box, so only a genuinely idle one sleeps. This hibernate/wake cycle is
what makes fleet-wide auto-previews (peak ~85–115 concurrently open) affordable
(~7–10× vs always-on). See hogland's `docs/PENS.md`.

Access is **tailnet-only** (PostHog VPN) — internal reviewers, no public URL.

## CLI

Pure stdlib + the SDK; run with `uv run` or plain `python`. Subcommands mirror
`bin/hobby-ci.py` so it drops into the same CI shape.

```bash
cd tools/hogbox-preview

# one-shot: provision (pen + box) + bring PostHog up, print the URL. The CI flow
# omits --frontend-dist and swaps the frontend in afterwards (below) so the FE
# build runs in parallel; the flag stays for a single-shot local build.
python -m hogbox_preview --host "$HOG_HOST" --name "preview-pr-$PR" up \
  --branch "pull/$PR/head" [--frontend-dist /path/to/frontend-dist.tgz] [--no-seed]

# deferred frontend swap onto the already-up box (what CI runs once the parallel
# build-frontend job finishes): resolves the live box by pen name, no restore.
python -m hogbox_preview --host "$HOG_HOST" --name "preview-pr-$PR" \
  swap-frontend --frontend-dist /path/to/frontend-dist.tgz

# granular / staged (reuse a box):
python -m hogbox_preview --host "$HOG_HOST" --name "preview-pr-$PR" create
python -m hogbox_preview --host "$HOG_HOST" --name "preview-pr-$PR" health
python -m hogbox_preview --host "$HOG_HOST" --name "preview-pr-$PR" destroy   # box + pen

# cron backstop: reap previews whose PR is closed (needs GITHUB_REPOSITORY + GH_TOKEN)
python -m hogbox_preview --host "$HOG_HOST" cleanup-stale
```

## The golden (and why it's fast)

The image-pull + full migrate is a one-time cost baked into the golden, not paid
per-PR. The golden is built on the **hogland** side by `scripts/posthog-preview-setup.sh`
via `snapshot-build` (a cold-boot seed — **never** `box snapshot` of a restored
box, which bakes the source TAP name and won't re-restore) and is left **warm**
(stack running) so restores resume a serving PostHog. It bakes `JS_URL=""` +
wildcard CSRF so any box's edge URL serves without a per-box rewrite. The DB
travels with the image it was migrated by — don't reuse a stale golden DB against
a newer image; re-bake instead. Timing details + the warm-vs-cold analysis live
in `STARTUP.md` and hogland's `docs/CHUNKFS_RESTORE_PERFORMANCE.md`.
