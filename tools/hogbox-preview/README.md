# hogbox-preview

Per-PR PostHog preview environments, the layer-agnostic way.

Spins PostHog up inside a disposable box and serves it at a clean public URL.
Today the box is a [hogland](https://github.com/PostHog/hogland) hogbox
(Firecracker microVM, reachable at `https://<box>.boxes.hogland.<env>.posthog.dev/`
over the tailnet). It used to be a DigitalOcean droplet (`bin/hobby-ci.py`), and
it may be something else next.

## The one idea: layer vs stack

The thing that changes when we swap providers is small and isolated:

- **Layer** (`backend.py`, `*_backend.py`) — _which box_: how to provision it,
  how to ssh in / which SDK to call, what its public URL is, how to destroy it.
  Swapping providers = one new `PreviewBackend`.
- **Stack** (`stack.py`) — _what runs in the box_: the PostHog docker-compose
  recipe (image, override, migrate, seed, health). It talks to the box only
  through the backend interface and **never changes when the layer changes**.

```python
from hogbox_preview import HoglandBackend, PostHogPreviewStack

backend = HoglandBackend(host="https://hogland.hedgehog-kitefin.ts.net")
url = PostHogPreviewStack(backend, branch="my-pr").bring_up()
print(url)  # https://box-….boxes.hogland.prod-us.posthog.dev/
```

## CLI

Pure stdlib; run with `uv run` or plain `python`. Subcommands mirror
`bin/hobby-ci.py` so it drops into the same CI shape.

```bash
cd tools/hogbox-preview

# one-shot: provision + bring PostHog up, print the URL
python -m hogbox_preview up --branch "$BRANCH" --host "$HOG_HOST"

# granular / staged (reuse a box):
python -m hogbox_preview create  --host "$HOG_HOST"
python -m hogbox_preview seed     --box-id box-xxxx
python -m hogbox_preview health   --box-id box-xxxx
python -m hogbox_preview destroy  --box-id box-xxxx
```

The hogland layer shells out to the `hogland` CLI for provisioning (it knows
`--web-port` → the box edge; the generated Python SDK doesn't surface that field
yet) and uses ssh for everything inside the box.

## The stack recipe (and why)

Proven end-to-end 2026-06-10. See `../../bin/hogbox-preview-NOTES.md` for the
full debugging history.

- **Run the published image as-is.** Two reasons we don't `build: .`: master's
  Dockerfile build is broken today (stale apt pin), _and_ the prod image runs
  its own baked code from `/code` — the dev-full `.:/app/posthog` mount is
  ignored (workdir is `/code`). So this is "run the image", like hobby. To
  preview a **specific PR**, pull that PR's image
  (`ghcr.io/posthog/posthog:pr-<n>` — what hobby-ci does), don't mount a branch.
- **Prod image → prod settings (`DEBUG=0`).** `DEBUG=1` pulls dev-only
  `INSTALLED_APPS` (e.g. `django_linear_migrations`) the prod image doesn't ship.
- **DB coherent with the image.** Migrate **both** Postgres and ClickHouse with
  the image's own migrations on a **fresh** DB. A golden's pre-migrated DB
  drifts from a different image version (we hit `column last_seen_at does not
exist`). So the DB is not reusable across image versions.
- **Single clean origin.** Serve on the box's one exposed port at its own URL so
  the SPA's absolute `/static` + `/api` paths resolve at the root.
- **Demo data via `manage.py generate_demo_data`** (the step hobby-ci uses) so
  the preview opens populated with a `test@posthog.com` / `12345678` login.
  Best-effort + needs a coherent image: bleeding `:master` can have a model
  ahead of its migrations and fail the seed (preview still serves, just empty).
  Toggle with `--no-seed`; pin a good image with `--image`.

### Fast restores (the right golden)

The image pull + migrate is a one-time cost. Bake a golden that pins **one
image** with its Postgres **and** ClickHouse already migrated by it (optionally
demo-data seeded) — then previews restore in seconds with no pull/migrate, and
the DB is coherent by construction. The DB must travel with the image it was
migrated by; don't reuse a stale golden DB against a newer image.
