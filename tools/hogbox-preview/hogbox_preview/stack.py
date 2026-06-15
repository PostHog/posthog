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
    ):
        self.backend = backend
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

    # --- public API ----------------------------------------------------------
    def bring_up(self) -> str:
        """Provision the box and bring PostHog up; return the public URL."""
        self.backend.provision()
        self.start_runtime()
        url = self.backend.web_url
        if self.branch:
            self.checkout_branch(self.branch)
        self.write_override(url)
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
        self.up_web()
        self.wait_for_health()
        return url

    # --- steps (each usable standalone, mirroring bin/hobby-ci.py) -----------
    def start_runtime(self) -> None:
        # The golden is baked with docker STOPPED (so the restore comes up with
        # a clean container runtime — a snapshot taken with docker running
        # resumes a corrupted one). Start it and wait for the daemon before any
        # docker/compose command. No-op if docker is already up.
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

    def write_override(self, url: str) -> None:
        # Only touch `web`: feed it the serving URL + prod-mode knobs. Leave
        # build/mount/command from dev-full alone (that's what runs the code).
        # An `image:` line is added ONLY when pinning a published image.
        lines = ["# Generated by tools/hogbox-preview.", "services:", "  web:"]
        if self.image:
            lines.append(f"    image: {self.image}")
        if self.image and self.mount:
            # Bind-mount PR backend source over the image's /code — no rebuild.
            # Compose concatenates volume lists across files, so dev-full's
            # .:/app/posthog stays and these are appended.
            lines.append("    volumes:")
            lines += [f"      - ./{src}:{dst}" for src, dst in self.MOUNTS]
        lines += [
            "    environment:",
            f"      - SITE_URL={url}",
            f"      - JS_URL={url}",
            f"      - EXTRA_CSRF_TRUSTED_ORIGINS={url}",
            "      - DISABLE_SECURE_SSL_REDIRECT=1",
            "      - DEBUG=0",
            # A preview serves one user, so one Unit worker is plenty — and the
            # image's entrypoint otherwise double-loads Django on every boot
            # (start→apply config→stop→restart), once per worker. Measured on a
            # restored golden: the stock 4-worker double-load is ~118s to first
            # /_health; one worker + a preloaded config is ~15-20s. The golden's
            # own bake sets the same (hogland scripts/posthog-preview-setup.sh).
            "      - NGINX_UNIT_APP_PROCESSES=1",
            "      - NGINX_UNIT_PRELOAD_CONFIG=true",
            f"      - SECRET_KEY={secrets.token_urlsafe(50)}",
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
            "for _ in $(seq 1 60); do "
            f"docker compose -f {self.COMPOSE} -f {self.OVERRIDE} ps --format '{{{{.Service}}}} {{{{.Status}}}}' "
            "| grep '^db ' | grep -q healthy && break; sleep 4; done"
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
