# Preview bring-up startup profiling

Why a per-PR preview takes a while to come up on a hogland hogbox, where the
time actually goes, and the levers that shrink it. Profiled 2026-06-15 against
prod-us, golden `snap-085a84dd47cd` (8 vCPU / 16 GiB / 100 GiB mirrored).

## Cold baseline: restore → `/_health`=200 ≈ 590s (~10 min)

Ground-truth per-phase wall time (in-box `date` markers, so poll granularity
doesn't distort it):

| phase                | cold     | what it does                                                                                     |
| -------------------- | -------- | ------------------------------------------------------------------------------------------------ |
| restore (VM resume)  | 38s      | server blocks until the box is `running`                                                         |
| ssh / exec ready     | 36s      | sshd/hogpanion start accepting after resume                                                      |
| `start-docker`       | **75s**  | `systemctl start docker`; containerd cold-reads its content store                                |
| `up-deps`            | 36s      | recreate 6 dep containers (the bake `down`s them), wait pg healthy                               |
| `migrate` (pg)       | **126s** | `run --rm web manage.py migrate` — a **no-op** on the golden (`No planned migration operations`) |
| `migrate_clickhouse` | **147s** | same, 281 CH migrations, all no-ops                                                              |
| `up-web`             | 2s       | create the web container                                                                         |
| web `/_health`       | **117s** | Nginx Unit + workers import `posthog.wsgi`, then serve                                           |

## Root cause: cold page-faulting through S3-backed chunkfs — not Django CPU

The rootfs is xfs on `/dev/vda`, which is chunkfs/NBD-backed. On a restore the
disk is lazily faulted: the **first** read of any byte fetches its chunk from the
S3-backed store. Everything that touches a lot of cold disk for the first time
pays for it:

- `django.setup()` is **~6s warm** (exec into a running container) but the first
  boot on a fresh restore — the `migrate` phase — is **~126s**. The delta is pure
  first-touch faulting of the python runtime + site-packages + posthog code.
  (FYI: the recent 12s→2s `setup()` win on master is real but orthogonal — it
  trims warm CPU; the preview's pain is the cold fault.)
- `start-docker` is 75s because containerd cold-reads its content store on start
  — the baked 8.7 GB posthog image + 6 dep images.
- Measured raw cold read throughput: **~48 MB/s** at the CLI default
  `--disk-mbps 125`, **~88 MB/s** unthrottled. So the **S3 chunk-fetch path
  (~88 MB/s) is the ceiling, not the disk cap** — `shared/types.go` notes NVMe
  "far exceeds 1000". Raising the cap helps a little (start-docker 75→53s,
  migrate 126→108s) but can't beat the backing-store rate.
- 16 GiB RAM also causes page-cache eviction between phases under the running
  stack, so pages warmed by one phase get re-faulted by the next.

> **Trap:** the production tool uses the SDK, which sends `disk_mbps=0`
> (unthrottled). Only the `hogland` **CLI** defaults to `125`. Don't profile via
> the CLI and conclude the disk is the cap.

## Validated levers

- **Web: `NGINX_UNIT_APP_PROCESSES=1` + `NGINX_UNIT_PRELOAD_CONFIG=true` → first
  `/_health` 118s → ~18s.** The biggest cheap win. `bin/docker-server-unit` runs
  **4** Unit workers and, when `PRELOAD_CONFIG` is unset, **double-loads** Django
  per worker (start → apply config → stop → restart) = 8 full imports. A preview
  serves one user; one worker + a preloaded config kills the redundancy. Applied
  in `stack.py` `write_override` and in the golden's own bake
  (hogland `scripts/posthog-preview-setup.sh`).
- **Tighter poll intervals** (`run_long`/`wait_http_ok` 10s → 3s): each completed
  step otherwise sits on up to 10s of dead air before we notice; a handful of
  steps adds up.
- **Don't bother combining migrate + migrate_clickhouse** — measured ~260s
  combined vs ~252s separate. They fault different working sets and CH queries
  hit a cold CH server; combining buys nothing.
- **Skipping migrate on a no-migration PR** just moves the ~90s import-fault to
  the web phase (something has to fault the import set once). Floor with the
  cheap wins ≈ 220s.

## The structural fix: a warm, docker-running golden

The cheap wins bottom out around 220s because, on a cold-on-disk snapshot, three
costs are irreducible: containerd cold-read (~60s), the import working-set fault
(~90s), and restore+ssh (~70s). To beat that, **don't snapshot the golden cold**.

Today the bake ends with `docker compose down` + `systemctl stop docker` so the
restore "cold-starts a clean runtime." That was forced by a corruption bug —
concurrent NBD writes racing chunkfs `WriteAt`'s read-modify-write, which tore
every docker-running snapshot (hogland #302, now **fixed**). With that gone, bake
the golden with the stack **up, healthy, and cache-warm** instead:

- restore **resumes a serving PostHog** — no containerd cold-start, no cold
  import faults. Page cache is guest RAM, restored via UFFD from a node-local
  memory snapshot (fast), not re-fetched from S3 disk chunks.
- delta-migrate for a PR runs via `exec` into the already-warm container (~20s)
  instead of a cold `run --rm` (~126s).

**Validated 2026-06-15** (alias `posthog-preview-golden-warm`, `snap-e82258df6119`,
baked via `snapshot-build`): a warm restore reaches external `/_health`=200 in
**~32s** (21s VM resume + ~11s) with **zero bring-up** — docker resumes `active`,
all 7 containers resume in place, the real SPA at `/` and the seeded `/login`
serve, `/_health` is stable, and **0 containers crash-loop on resume**. vs ~590s
cold. The recipe is now the default in hogland `scripts/posthog-preview-setup.sh`
(bakes warm instead of `down` + stop-docker).

Two hard constraints learned the hard way:

- The golden **must** be built by `snapshot-build` (cold-boot seed). `box snapshot`
  of a _restored_ box bakes in the source's TAP name and fails to re-restore
  (`Open tap device ... kn-box-XXXX`). So there's no "warm a box then snapshot it"
  shortcut — the warm state has to be produced inside the cold-boot bake.
- Cold-boot bakes need real host NVMe (fresh rootfs + 8.7GB image pull). A node
  with a stuck/abandoned box wedges placement with `no space left on device` —
  which fails restores too. Watch node disk; reap abandoned boxes.

What the per-PR tool still pays on a warm golden: it rewrites `SITE_URL` to the
box's edge URL and recreates **only** web (warm import + 1 worker ≈ 18s); `start
docker` / `up deps` are idempotent no-ops on the running stack; delta-migrate (if
the PR touches migrations) runs warm (~20s). So a real preview lands ~60–90s, not
32s — the 32s is the golden's own resume. A follow-on win is making `SITE_URL`
per-box without a web recreate, which would bring real previews toward ~32s too.

## Wake-on-request (shipped): warm restore of a hibernated preview

The same warm-restore physics enable the end goal: hibernate an idle preview
(snapshot the _ready_ box — stack up, PR code current — then destroy it, zero
node cost) and **wake it on the first HTTP request**. Because the snapshot is the
fully-brought-up preview, waking is a warm restore, not a rebuild: **~30–40s to
serving even on a cold node** (UFFD restores the page cache; the serving working
set faults in lazily — see hogland `docs/CHUNKFS_RESTORE_PERFORMANCE.md`), vs the
~250s to rebuild from the golden. **This is now live end-to-end:** hogland #319's
pen resolver + the wake-on-request interstitial at that 503 seam (#325), the
server-side hibernate/wake verbs, the idle-TTL reaper that auto-hibernates an
`on_idle=hibernate` pen (#329), and the pen-delete cascade that reaps the box +
hibernate snapshot on teardown (#328). The former blocker — hibernate snapshots
a _restored_ box, which baked the source TAP name and wouldn't re-restore (C7) —
was fixed by the TAP-remap (#322). So an idle preview now sleeps after its
`ttl_seconds` and wakes on the next visit, with no preview-tool changes needed
(this tool already tags its pens `on_idle=hibernate` / `wake=on-request`).

## Gotchas — baking & restoring the golden

Hard-won in PR #308 (the golden bake) + the warm-golden work. The bake script
encodes them, but they're easy to regress, so they live here too:

- **`compose run` has no `--no-build`.** Only a _present_ image stops it from
  silently starting dev-full's ~20-min `build: .`. Pull the image upfront and
  hard-fail if it's absent — don't discover the build at the migrate step.
- **Never `compose restart web`.** Nginx Unit installs its `*:8000` listener only
  on a fresh container's first boot (`/var/lib/unit` empty); a restart skips it
  and comes up with `listeners: {}` serving nothing. Recreate with a clean `up`
  (`--force-recreate` if web must be replaced).
- **Restore sizing must match the baked spec exactly** — 8 vCPU / 16384 MiB /
  100 GiB / mirrored. "Omit to inherit" is unreliable server-side; a mismatch is
  rejected. (NB: the SDK sends `disk_mbps=0` = unthrottled; the `hogland` CLI
  defaults to `125` — a trap if you profile via the CLI.)
- **Build via `snapshot-build` (cold-boot seed), never `box snapshot` of a
  restored box** — the latter bakes the source TAP name and won't re-restore
  (`Open tap device ... kn-box-XXXX`).
- **Watch node disk.** Cold-boot bakes need real host NVMe (fresh rootfs + ~8.7GB
  image pull). A stuck/abandoned box wedges placement with `no space left on
device`, which fails restores too. Abandoned _running_ boxes aren't auto-reaped.
- **No-TTY seed box → `DEBIAN_FRONTEND=noninteractive`.** apt's `-y` doesn't
  suppress debconf prompts (tzdata/locale); without it a bake can hang.
- **Hard-fail the postgres wait loop.** A silent timeout falls through to a
  confusing psycopg2 error at migrate instead of a clear "pg never healthy".
- **Don't hardcode container names** (`posthog-db-1`) — exec via the compose
  service (`db`) so it tracks `COMPOSE_PROJECT_NAME`.
- **Shrink + flush before snapshot:** `apt-get clean` + drop `/var/lib/apt/lists`
  (re-fetches in seconds, but costs every restore real chunk I/O if baked in),
  and `sync` so the pause-time flush has the smallest backlog.
- **32 KiB bootstrap-script cap** (MMDS budget) — a guard test covers the setup
  script; keep edits under it or bakes fail at runtime.
- **`--web-port` needs the CLI `Expose`-forwarding fix (#309)** — older CLIs
  silently drop exposure, so the box gets no edge URL.
- **`:master` can ship a model ahead of its migrations** — the defensive
  `last_seen_at` ALTER stays until the image is migration-coherent.

## Reproducing

`~/workspace/startup-profiling/preview/harness.py` — provisions via the `hogland`
CLI (Tailscale identity, no token), drives every phase over SSH-as-`hog`, and
records ground-truth per-phase timing via in-box `date` markers. `restore` /
`bringup` / `fast-bringup` / `bringup-prewarm` / `phase <name>` / `health-fine`.
