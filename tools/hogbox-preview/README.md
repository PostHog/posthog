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

- **Published image, not a local build.** master's `build: .` is broken today
  (stale apt pin), so we pull `ghcr.io/posthog/posthog:master` and mount the
  live source over it — same dev-full shape, no build.
- **Prod image → prod settings (`DEBUG=0`).** `DEBUG=1` pulls dev-only
  `INSTALLED_APPS` (e.g. `django_linear_migrations`) the prod image doesn't ship.
- **Single clean origin.** Serve on the box's one exposed port at its own URL so
  the SPA's absolute `/static` + `/api` paths resolve at the root.
- **Demo data via `manage.py n`** (the `setup_dev` successor) — same step
  hobby/sandbox use, so the preview opens to a populated instance with a
  `test@posthog.com` / `12345678` login instead of an empty preflight. Toggle
  with `--no-seed`.

### Fast restores (follow-up)

The image pull + migrate is a one-time cost. Bake them into a new golden
snapshot (image pre-pulled, DB migrated) and future previews restore in seconds
with no pull/migrate. Until then the first `up` does the slow steps once.
