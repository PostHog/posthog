"""The preview *stack* — provider-agnostic.

``PostHogPreviewStack`` knows how to bring PostHog up inside any
``PreviewBackend``: build from the checkout, migrate, seed demo data, wait for
health. It talks to the box only through ``backend.exec`` / ``write_file`` /
``run_long`` / ``wait_http_ok`` — it never knows or cares whether the box is a
hogbox or a droplet. Swapping the layer changes the backend, not this file.

Recipe (build-from-checkout — the dev-full native path):
  - dev-full's ``web`` is ``build: .`` from the repo, so the running code is
    whatever is checked out. To preview a PR: ``git checkout`` the PR branch and
    rebuild the image (``docker compose build``). No per-PR PUBLISHED image —
    the build is local and incremental (warm Docker + turbo cache from the
    golden's master build), so it's not the cold 20-min build every time.
    Earlier this path was blocked by a stale apt pin in the Dockerfile; that's
    fixed on master.
  - The Dockerfile's frontend-build stage compiles the SPA as part of the
    image build, so one rebuild covers front AND back — no separate pnpm step.
  - ``web`` runs from the image's ``WORKDIR /code`` (the dev-full
    ``.:/app/posthog`` bind-mount is NOT the working dir), so the rebuild — not
    the mount — is what swaps the code in. DEBUG=0: the built image is the prod
    Dockerfile, and DEBUG=1 expects dev-only INSTALLED_APPS it doesn't ship.
  - FUTURE (hot-mount): the goal is live-mounted code, no per-PR rebuild. That
    means running web from the bind-mount instead of /code — override
    ``working_dir: /app/posthog`` + the base ``./bin/start-backend &
    ./bin/start-frontend`` command (vite watcher), and bake node_modules + the
    venv into the host repo so the mount carries them. Rebuild-from-checkout is
    the baseline we validate first; hot-mount is the iteration on top.
  - The DB must be COHERENT with the built code: migrate Postgres AND ClickHouse
    on a fresh DB (``reset_db`` when baking a golden). A restored golden's
    pre-migrated DB only needs the PR's *delta* migrations on top.
  - seed demo data with ``manage.py generate_demo_data`` (the step hobby-ci
    uses) so the preview opens populated with a login. Best-effort.
  - ``image`` is an ESCAPE HATCH: pass a published tag to skip the build and run
    that image instead (e.g. when a box can't build, or to pin a known-good).
"""

from __future__ import annotations

import sys
import secrets

from .backend import PreviewBackend


class PostHogPreviewStack:
    # No default image: build from the checkout. Pass `image` to pin/skip-build.
    IMAGE = None
    REPO_DIR = "/home/hog/posthog"
    COMPOSE = "docker-compose.dev-full.yml"
    OVERRIDE = "docker-compose.preview.yml"
    # Dependency services (published images, pulled by `up`).
    DEPS = ["db", "redis7", "clickhouse", "zookeeper", "kafka", "objectstorage"]
    # App services built from the checkout. web shares its image with the other
    # build: . services, so building web warms the layer cache for all of them.
    BUILD_SERVICES = ["web"]

    def __init__(
        self,
        backend: PreviewBackend,
        *,
        branch: str | None = None,
        image: str | None = None,
        repo_dir: str | None = None,
        seed_demo_data: bool = True,
        reset_db: bool = False,
    ):
        self.backend = backend
        self.branch = branch
        # None -> build from the checkout; a tag -> run that published image.
        self.image = image or self.IMAGE
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
        self.up_services()
        self.migrate()
        if self.seed_demo_data:
            # Best-effort: a transient build/model issue shouldn't sink an
            # otherwise-good preview — it just opens empty.
            try:
                self.generate_demo_data()
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"[hogbox-preview] demo-data seeding skipped (preview still usable): {e}\n")
        self.wait_for_health()
        return url

    # --- steps (each usable standalone, mirroring bin/hobby-ci.py) -----------
    def checkout_branch(self, branch: str) -> None:
        self.backend.run_long(
            f"cd {self.repo_dir} && git fetch --depth 1 origin {branch} && git checkout --force FETCH_HEAD",
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
        lines += [
            "    environment:",
            f"      - SITE_URL={url}",
            f"      - JS_URL={url}",
            f"      - EXTRA_CSRF_TRUSTED_ORIGINS={url}",
            "      - DISABLE_SECURE_SSL_REDIRECT=1",
            "      - DEBUG=0",
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
        # Only used with the `image` escape hatch. ghcr pulls flake (TLS
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

    def up_services(self) -> None:
        services = " ".join([*self.DEPS, "web"])
        self.backend.run_long(self._compose(f"up -d --no-build {services}"), name="up", timeout=900)

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
        # web must be (re)started after migrate/seed so unit re-checks health.
        self.backend.run_long(self._compose("restart web"), name="restart", timeout=300)
        self.backend.wait_http_ok("/_health", expect=200, timeout=600)

    # --- internal ------------------------------------------------------------
    def _compose(self, args: str) -> str:
        return f"cd {self.repo_dir} && docker compose -f {self.COMPOSE} -f {self.OVERRIDE} {args}"
