"""The preview *stack* — provider-agnostic.

``PostHogPreviewStack`` knows how to bring PostHog up inside any
``PreviewBackend``: build from the checkout, migrate, seed demo data, wait for
health. It talks to the box only through ``backend.exec`` / ``write_file`` /
``run_long`` / ``wait_http_ok`` — it never knows or cares whether the box is a
hogbox or a droplet. Swapping the layer changes the backend, not this file.

Recipe (mount-over-image — the default, ~minutes per PR):
  - Run the ready-made published image (``ghcr.io/posthog/posthog:master``) and
    bind-mount the PR's backend source (``posthog``/``ee``/``products``) over the
    image's ``/code``. The image is the prod Dockerfile: it runs from
    ``WORKDIR /code`` via ``./bin/docker-server-unit`` with the frontend baked at
    ``/code/frontend/dist``. Mounting the source swaps the BACKEND code live — no
    per-PR build. (Frontend stays at the image's version; frontend hot-mount is a
    later iteration.) DEBUG=0 is required: the prod image lacks DEBUG-only apps.
  - NEVER ``restart`` the web container. Nginx Unit applies its ``*:8000``
    listener only on a fresh container's first boot (``/var/lib/unit`` empty); a
    ``restart`` finds it non-empty, skips the listener, and the app comes up with
    ``listeners: {}`` — nothing serves on 8000. ``wait_for_health`` just waits on
    the clean ``up`` (use ``--force-recreate`` if web ever needs replacing).
  - DB coherence: the restored golden's DB was migrated + seeded against the same
    image tag, so a restore only needs the PR's *delta* migrations on top
    (``migrate`` + ``migrate_clickhouse``). Reseeding is skipped — the golden is
    already seeded (CI passes ``--no-seed``).
  - ``build`` ESCAPE HATCH: pass ``image=None`` to build ``web`` from the
    checkout instead (``build: .`` — cold ~20 min; used when baking a golden, or
    to pin nothing). ``reset_db`` wipes pg+clickhouse so they migrate fresh
    against the built code. ``compose run`` has no ``--no-build`` flag (that's
    ``up``-only); what prevents a build is the image being present, so always
    pull/pin the image before any ``run``.
"""

from __future__ import annotations

import sys
import secrets

from .backend import PreviewBackend

# The tool's web override must reproduce the golden's baked preview env (hogland
# scripts/posthog-preview-setup.sh) — constant across previews so web's config
# never drifts per-box. JS_URL="" makes the SPA load assets relative to the
# request origin; the wildcard CSRF origin trusts every box's edge host for the
# login POST. One recipe then serves any box at its own edge URL.
# Built as a single comma-separated string (Django's get_list() splits on commas)
# — a join, not a tuple, so there's no ambiguity about what reaches the env.
_CSRF_TRUSTED_ORIGINS = ",".join(f"https://*.boxes.hogland.{env}.posthog.dev" for env in ("dev", "prod-us", "prod-eu"))
# PostHog's prod settings refuse to boot on the default SECRET_KEY, so the
# override must supply one (the migrate `run --rm web` one-off needs it too).
#
# It MUST be random per preview, NOT a shared constant. Previews are served on
# PUBLIC URLs (pen-<id>.boxes.hogland.<env>.posthog.dev) — the old
# "tailnet-only" assumption was stale — so a globally derivable SECRET_KEY lets
# anyone forge session cookies against every preview. We mint one random key per
# provision (see __init__) and pin it in the compose override so ALL of a
# single preview's processes share it, while different previews never do. A
# re-provision of the same PR rotates the key; that's fine — preview logins are
# throwaway demo sessions, so dropping them on re-provision is acceptable.


class PostHogPreviewStack:
    # Default: run the ready-made published image and mount PR source over it.
    # Pass image=None to fall back to the build-from-checkout escape hatch.
    IMAGE = "ghcr.io/posthog/posthog:master"
    REPO_DIR = "/home/hog/posthog"
    COMPOSE = "docker-compose.dev-full.yml"
    OVERRIDE = "docker-compose.preview.yml"
    # Dependency services (published images, pulled by `up`).
    DEPS = ["db", "redis7", "clickhouse", "zookeeper", "kafka", "objectstorage"]
    # App services built from the checkout (build escape hatch only). web shares
    # its image with the other build: . services, so building web warms them all.
    BUILD_SERVICES = ["web"]
    # PR backend source bind-mounted over the image's /code (backend hot-mount).
    # The frontend stays baked in the image; mounting these swaps backend live.
    MOUNTS = [("posthog", "/code/posthog"), ("ee", "/code/ee"), ("products", "/code/products")]

    def __init__(
        self,
        backend: PreviewBackend,
        *,
        branch: str | None = None,
        image: str | None = None,
        repo_dir: str | None = None,
        seed_demo_data: bool = True,
        reset_db: bool = False,
        mount: bool = True,
        frontend_dist_tar: str | None = None,
    ):
        self.backend = backend
        # One random Django SECRET_KEY per stack (i.e. per provisioned box). Pinned
        # into the compose override so every process of THIS preview shares it, and
        # never shared across previews — see the module-level note above.
        self.secret_key = secrets.token_hex(32)
        self.branch = branch
        # Default (None) -> the ready-made image; "" -> build-from-checkout escape
        # hatch; any tag -> run that published image.
        self.image = self.IMAGE if image is None else image
        # Bind-mount PR source over the image's /code (only meaningful with a
        # pinned image — the build path bakes the code in, so no mount needed).
        self.mount = mount
        self.repo_dir = repo_dir or self.REPO_DIR
        self.seed_demo_data = seed_demo_data
        # reset_db wipes pg + clickhouse before migrating, so the DB is migrated
        # fresh against the built code rather than inheriting a snapshot's
        # drifted DB. Set when baking a golden; a restore-and-delta leaves False.
        self.reset_db = reset_db
        # Optional gzipped tar of a prebuilt frontend/dist (built in CI with the
        # Turbo cache). When set, swap_frontend serves the PR's own frontend
        # instead of the golden image's :master SPA. None => keep :master.
        self.frontend_dist_tar = frontend_dist_tar

    # --- public API ----------------------------------------------------------
    def bring_up(self) -> str:
        """Provision the box and bring PostHog up; return the public URL."""
        self.backend.provision()
        self.start_runtime()
        url = self.backend.web_url
        if self.branch:
            self.checkout_branch(self.branch)
        self.write_override()
        if self.image:
            self.pull_image()  # escape hatch: run a published image, skip build
        else:
            self.build_app()  # native path: build the checkout (PR code)
        if self.reset_db:
            self.reset_database()
        # Migrate (and seed) BEFORE web serves: web can't be restarted to pick up
        # a PR's delta migrations (the Unit-listener gotcha), so the schema must
        # be ready before the serving container boots.
        self.up_deps()
        self.migrate()
        if self.seed_demo_data:
            # Best-effort: a transient build/model issue shouldn't sink an
            # otherwise-good preview — it just opens empty.
            try:
                self.generate_demo_data()
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"[hogbox-preview] demo-data seeding skipped (preview still usable): {e}\n")
        if self.frontend_dist_tar:
            # Serve the PR's frontend (else it's the golden's :master SPA). Must
            # run before up_web so the fresh web container reads the new index
            # template + collected statics.
            self.swap_frontend()
        self.up_web()
        self.wait_for_health()
        return url

    # --- steps (each usable standalone, mirroring bin/hobby-ci.py) -----------
    def start_runtime(self) -> None:
        # Ensure docker is up before any compose command. The current golden is
        # baked WARM (stack already running — see tools/hogbox-preview/STARTUP.md),
        # so this is a no-op there; it stays as a safety net for a cold/stopped
        # golden or a box whose daemon didn't auto-start. Idempotent either way —
        # returns once `docker info` answers.
        self.backend.run_long(
            "systemctl start docker; "
            "for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 2; done; "
            "docker info >/dev/null 2>&1",
            name="start-docker",
            timeout=180,
        )

    def checkout_branch(self, branch: str) -> None:
        # The box's exec API runs as root while the repo is hog-owned, so git
        # flags "dubious ownership" — scope a safe.directory exception per
        # command. (The rest of the stack runs as root too, matching how the
        # golden's setup script built it.)
        safe = f"git -c safe.directory={self.repo_dir}"
        self.backend.run_long(
            f"cd {self.repo_dir} && {safe} fetch --depth 1 origin {branch} && {safe} checkout --force FETCH_HEAD",
            name="checkout",
            timeout=600,
        )

    def write_override(self) -> None:
        # Reproduce the golden's baked web env (hogland
        # scripts/posthog-preview-setup.sh) so this block carries no per-box
        # value and never drifts between previews. A web recreate still happens
        # in up_web — but only to bind-mount the PR's backend source over the
        # image's /code (you can't add a mount to a running container). On the
        # warm golden that's a ~18s warm import (1 Unit worker + preloaded
        # config), not the old ~120s cold rebuild; #315's win is making that
        # recreate warm and serving the frontend relative (JS_URL=""), not
        # removing it. Keeping the env constant means web only ever recreates
        # for the mount, never for config drift.
        lines = ["# Generated by tools/hogbox-preview.", "services:", "  web:"]
        if self.image:
            lines.append(f"    image: {self.image}")
        if self.image and self.mount:
            # Bind-mount PR backend source over the image's /code — no rebuild.
            # Compose concatenates volume lists across files, so dev-full's
            # .:/app/posthog stays and these are appended.
            lines.append("    volumes:")
            mounts = list(self.MOUNTS)
            if self.frontend_dist_tar:
                # Serve the PR's frontend too: its built dist (the SPA index
                # template) + the statics collectstatic writes into staticfiles/.
                # Both are mounted so swap_frontend's `run` container and the
                # serving web container share them — static is served by
                # WhiteNoise from staticfiles/, NOT frontend/dist, hence both.
                mounts += [("frontend/dist", "/code/frontend/dist"), ("staticfiles", "/code/staticfiles")]
            lines += [f"      - ./{src}:{dst}" for src, dst in mounts]
        lines += [
            "    environment:",
            # SITE_URL is a cosmetic placeholder (absolute links in emails etc.);
            # serving is driven by JS_URL="" (relative assets) + the wildcard
            # CSRF origin, so the box's own edge host serves with no per-box env.
            "      - SITE_URL=http://localhost:8000",
            "      - JS_URL=",
            f"      - EXTRA_CSRF_TRUSTED_ORIGINS={_CSRF_TRUSTED_ORIGINS}",
            "      - DISABLE_SECURE_SSL_REDIRECT=1",
            "      - DEBUG=0",
            # Random per-preview key (see self.secret_key) — PostHog's prod
            # settings refuse to boot on the default, and the migrate one-off
            # (compose run --rm web) needs it too. Not shared across previews, so
            # a public preview URL can't be used to forge sessions on another.
            f"      - SECRET_KEY={self.secret_key}",
            # A preview serves one user, so one Unit worker is plenty — and the
            # image's entrypoint otherwise double-loads Django on every boot
            # (start→apply config→stop→restart), once per worker. Measured on a
            # restored golden: the stock 4-worker double-load is ~118s to first
            # /_health; one worker + a preloaded config is ~15-20s.
            "      - NGINX_UNIT_APP_PROCESSES=1",
            "      - NGINX_UNIT_PRELOAD_CONFIG=true",
        ]
        self.backend.write_file(f"{self.repo_dir}/{self.OVERRIDE}", "\n".join(lines) + "\n")

    def build_app(self) -> None:
        # `build: .` from the checkout — bakes the PR's code (front + back) into
        # the image. Cold this is ~15-25 min; on a restored golden the Docker
        # layer + turbo cache make it incremental.
        services = " ".join(self.BUILD_SERVICES)
        self.backend.run_long(self._compose(f"build {services}"), name="build", timeout=2700)

    def pull_image(self, *, attempts: int = 3) -> None:
        # The default path: fetch the ready-made image. Fast/no-op if a golden
        # already baked it in; otherwise pulls. ghcr pulls flake (TLS
        # handshake timeouts mid-layer); retry — docker resumes from pulled
        # layers, so a retry is cheap.
        last: Exception | None = None
        for _ in range(attempts):
            try:
                self.backend.run_long(f"docker pull {self.image}", name="pull", timeout=1800)
                return
            except RuntimeError as e:
                last = e
        raise RuntimeError(f"docker pull {self.image} failed after {attempts} attempts: {last}")

    def reset_database(self) -> None:
        # Drop the snapshot's pre-migrated DB so migrate() rebuilds it fresh and
        # coherent with the built code. Postgres keeps its data in a named volume
        # that survives container recreation, so the volume must be removed by
        # name; ClickHouse is volume-less, so recreating its container is enough.
        cmd = (
            f"cd {self.repo_dir} && "
            f"docker compose -f {self.COMPOSE} -f {self.OVERRIDE} stop db clickhouse web ; "
            f"docker compose -f {self.COMPOSE} -f {self.OVERRIDE} rm -f db clickhouse web ; "
            "docker volume rm posthog_postgres-15-data || true"
        )
        self.backend.run_long(cmd, name="reset-db", timeout=300)

    def up_deps(self) -> None:
        # Start the dependency services and wait for postgres to report healthy
        # before migrating. Idempotent: on a restored golden whose stack is
        # already running, `up` is a no-op for already-current containers.
        services = " ".join(self.DEPS)
        script = (
            f"cd {self.repo_dir} && docker compose -f {self.COMPOSE} -f {self.OVERRIDE} up -d --no-build {services} && "
            "healthy=0; for _ in $(seq 1 60); do "
            f"docker compose -f {self.COMPOSE} -f {self.OVERRIDE} ps --format '{{{{.Service}}}} {{{{.Status}}}}' "
            "| grep '^db ' | grep -q healthy && { healthy=1; break; }; sleep 4; done; "
            '[ "$healthy" = 1 ] || { echo "db never became healthy" >&2; exit 1; }'
        )
        self.backend.run_long(script, name="up-deps", timeout=900)

    def up_web(self) -> None:
        # Clean `up` (never `restart` — Unit-listener gotcha). --no-build reuses
        # the pulled image; the override mounts PR source over its /code.
        self.backend.run_long(self._compose("up -d --no-build web"), name="up-web", timeout=900)

    def migrate(self) -> None:
        # PostHog needs both: Postgres (schema) and ClickHouse (events DB +
        # tables). ClickHouse must be migrated before demo-data generation,
        # which writes events to it.
        self.backend.run_long(
            self._compose("run --rm -T web python manage.py migrate --noinput"),
            name="migrate",
            timeout=1800,
        )
        self.backend.run_long(
            self._compose("run --rm -T web python manage.py migrate_clickhouse"),
            name="migrate-clickhouse",
            timeout=1800,
        )

    def generate_demo_data(self) -> None:
        # Same command hobby-ci uses (bin/hobby-ci.py). Seeds a demo org + the
        # test@posthog.com / 12345678 login so the preview opens populated.
        # (`manage.py n` is a dev-only alias, not registered in this image.)
        self.backend.run_long(
            self._compose("run --rm -T web python manage.py generate_demo_data"),
            name="seed",
            timeout=1800,
        )

    def swap_frontend(self) -> None:
        # Serve the PR's OWN frontend. The dist is built in CI (Depot + Turbo
        # cache) and handed in as a gzipped tar; drop it into the box's
        # frontend/dist (bind-mounted over /code/frontend/dist by write_override)
        # and re-run collectstatic so WhiteNoise serves the PR's hashed chunks
        # from the (also-mounted) staticfiles/. Static is served from
        # staticfiles/, NOT frontend/dist — so collectstatic is mandatory.
        # STATIC_COLLECTION=1 skips the prod SECRET_KEY guard; the version skip
        # mirrors the image's own collectstatic. Deps are already up (up_deps ran)
        # so settings import is fine; collectstatic itself needs no live DB.
        import pathlib

        tar = pathlib.Path(self.frontend_dist_tar).read_bytes()
        self.backend.write_file(f"{self.repo_dir}/frontend/dist.tgz", tar)
        compose = f"docker compose -f {self.COMPOSE} -f {self.OVERRIDE}"
        # CI tars the dist with `-C frontend dist`, so its members are rooted at
        # `dist/`; strip that leading level on extract or the SPA double-nests to
        # frontend/dist/dist/ and collectstatic finds nothing.
        script = (
            f"cd {self.repo_dir} && "
            "rm -rf frontend/dist && mkdir -p frontend/dist staticfiles && "
            "tar xzf frontend/dist.tgz -C frontend/dist --strip-components=1 && "
            f"{compose} run --rm -T -e STATIC_COLLECTION=1 -e SKIP_SERVICE_VERSION_REQUIREMENTS=1 "
            "web python manage.py collectstatic --noinput"
        )
        self.backend.run_long(script, name="frontend", timeout=900)

    def wait_for_health(self) -> None:
        # Do NOT `restart web` with the pinned image: Nginx Unit binds its :8000
        # listener only on a fresh container's first boot (/var/lib/unit empty);
        # a restart skips it and leaves `listeners: {}`, so nothing serves.
        # up_services already brought web up cleanly — just wait for it to serve.
        # Django is a heavy import; first health can take ~7 min.
        self.backend.wait_http_ok("/_health", expect=200, timeout=900)

    # --- internal ------------------------------------------------------------
    def _compose(self, args: str) -> str:
        return f"cd {self.repo_dir} && docker compose -f {self.COMPOSE} -f {self.OVERRIDE} {args}"
