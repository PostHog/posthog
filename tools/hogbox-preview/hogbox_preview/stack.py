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

from . import timing
from .backend import PreviewBackend

# The tool's web override MUST stay in sync with the golden bake script (hogland
# scripts/posthog-preview-setup.sh): both write docker-compose.preview.yml, and
# regenerating it here CLOBBERS the golden's baked copy — so anything the bake
# adds (env, services) must be mirrored here or a per-PR override drops it. That
# drift is exactly what broke previews fleet-wide from 2026-07-06 to 2026-07-10
# (missing PERSONHOG_ADDR -> "personhog client not configured" 500s); see
# write_override for the full post-mortem. JS_URL="" makes the SPA load assets
# relative to the request origin; the wildcard CSRF origin trusts every box's
# edge host for the login POST. One recipe then serves any box at its own edge
# URL.
# Built as a single comma-separated string (Django's get_list() splits on commas)
# — a join, not a tuple, so there's no ambiguity about what reaches the env.
_CSRF_TRUSTED_ORIGINS = ",".join(f"https://*.boxes.hogland.{env}.posthog.dev" for env in ("dev", "prod-us", "prod-eu"))
# The seeded demo login. These are the defaults of posthog's
# `manage.py generate_demo_data` (--email / --password, see
# posthog/management/commands/generate_demo_data.py), which generate_demo_data()
# runs unchanged. Not importable here — the tool runs in an SDK-only env with no
# posthog Django on the path — so they're duplicated with that source named. If
# the seed defaults ever change, change these too.
_DEMO_EMAIL = "test@posthog.com"
_DEMO_PASSWORD = "12345678"

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
        self.deep_health()
        return url

    def swap_frontend_only(self) -> str:
        """Lay the PR's frontend onto an ALREADY-up preview box; return its URL.

        The second half of the parallel CI flow: bring_up() first brings the box
        healthy on the golden's :master SPA with NO dist (so it can run the
        moment the box is restored, in parallel with the runner building the PR
        frontend), then — once that build finishes — this swaps the freshly-built
        dist in. It reuses the exact override + collectstatic + web-recreate the
        single-pass bring_up runs after seeding, so there's no second recipe to
        keep in sync. Attaches to the live box by pen/name rather than restoring
        a new one.
        """
        if not self.frontend_dist_tar:
            raise RuntimeError("swap_frontend_only requires a frontend dist (pass --frontend-dist)")
        self.backend.attach()
        # Keep the box's existing SECRET_KEY: recreating web in up_web must NOT
        # rotate the key bring_up already migrated + seeded under, or anything it
        # wrote encrypted becomes undecryptable (and any live session drops).
        self._reuse_existing_secret_key()
        # Rewrite the override so it now carries the frontend/dist + staticfiles
        # mounts (write_override only adds them when a dist is set), lay the dist
        # in + re-run collectstatic into the mounted staticfiles/, then recreate
        # web so the fresh container reads the PR's index + statics.
        self.write_override()
        self.swap_frontend()
        self.up_web()
        self.wait_for_health()
        return self.backend.web_url

    def _reuse_existing_secret_key(self) -> None:
        """Adopt the SECRET_KEY the box already runs with (read from its override)
        so a deferred swap doesn't rotate it. Falls back to the freshly-minted
        key when the override can't be read — shouldn't happen post-bring_up, but
        a random key is a safe default either way."""
        r = self.backend.exec(
            f"sed -n 's/.*SECRET_KEY=//p' {self.repo_dir}/{self.OVERRIDE} 2>/dev/null | head -n1",
            timeout=60,
        )
        key = r.stdout.strip()
        if key:
            self.secret_key = key

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
        timing.stage(f"in-box PR checkout ({branch})")
        safe = f"git -c safe.directory={self.repo_dir}"
        self.backend.run_long(
            f"cd {self.repo_dir} && {safe} fetch --depth 1 origin {branch} && {safe} checkout --force FETCH_HEAD",
            name="checkout",
            timeout=600,
        )

    def write_override(self) -> None:
        # This override MUST stay in sync with hogland's
        # scripts/posthog-preview-setup.sh (the golden bake script). Both write
        # the same docker-compose.preview.yml; the bake bakes it into the golden,
        # this regenerates it per PR — and regenerating it CLOBBERS the baked one.
        # When the two drifted, previews broke fleet-wide: the bake added
        # PERSONHOG_ADDR + the personhog services on 2026-07-06 (master's Django
        # hard-requires the personhog service for group-type lookups since #65968
        # — require_personhog_client() raises "personhog client not configured"
        # without it), this file didn't, and every preview 500'd on
        # /api/projects/@current/ (and environment/@current, team create, some
        # HogQL paths) from 2026-07-06 to 2026-07-10 until this was fixed.
        #
        # A web recreate still happens in up_web — but only to bind-mount the PR's
        # backend source over the image's /code (you can't add a mount to a
        # running container). On the warm golden that's a ~18s warm import (1 Unit
        # worker + preloaded config), not the old ~120s cold rebuild; #315's win
        # is making that recreate warm and serving the frontend relative
        # (JS_URL=""), not removing it. Keeping the env constant means web only
        # ever recreates for the mount, never for config drift.
        timing.stage("write compose override (backend mount)")
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
            # master's Django hard-requires the personhog service for group-type
            # lookups (require_personhog_client() raises "personhog client not
            # configured" without it — #65968). Same addr the dev/hobby composes
            # use; the router service is defined below. See write_override's note.
            "      - PERSONHOG_ADDR=personhog-router:50052",
        ]
        # Mirror the bake script's personhog service definitions (hogland
        # scripts/posthog-preview-setup.sh): dev-full.yml carries NO personhog
        # services (dev runs them via hogli), so define them here the way HOBBY
        # does — extend the base definitions and point the replica at the MAIN
        # posthog DB (persons live there for single-node deployments). The
        # golden's warm containers keep running regardless, but a cold/reset
        # path that `up`s the full project would lose them if they weren't here.
        # Tag matches the bake: the part of self.image after the last ':'.
        personhog_tag = self.image.rsplit(":", 1)[-1] if self.image else "master"
        lines += [
            "  personhog-replica:",
            "    extends:",
            "      file: docker-compose.base.yml",
            "      service: personhog-replica",
            f"    image: ghcr.io/posthog/posthog/personhog-replica:{personhog_tag}",
            "    environment:",
            "      PRIMARY_DATABASE_URL: postgres://posthog:posthog@db:5432/posthog",
            "  personhog-router:",
            "    extends:",
            "      file: docker-compose.base.yml",
            "      service: personhog-router",
            f"    image: ghcr.io/posthog/posthog/personhog-router:{personhog_tag}",
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
        timing.stage("start dependency services")
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
        timing.stage("start web container")
        self.backend.run_long(self._compose("up -d --no-build web"), name="up-web", timeout=900)

    def migrate(self) -> None:
        # PostHog needs both: Postgres (schema) and ClickHouse (events DB +
        # tables). ClickHouse must be migrated before demo-data generation,
        # which writes events to it.
        timing.stage("migrate start (postgres + clickhouse)")
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
        timing.stage("migrate done")

    def generate_demo_data(self) -> None:
        # Same command hobby-ci uses (bin/hobby-ci.py). Seeds a demo org + the
        # test@posthog.com / 12345678 login so the preview opens populated.
        # (`manage.py n` is a dev-only alias, not registered in this image.)
        timing.stage("seed demo data")
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

        timing.stage("frontend swap start (upload dist)")
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
        timing.stage("frontend swap done (collectstatic done)")

    def wait_for_health(self) -> None:
        # Do NOT `restart web` with the pinned image: Nginx Unit binds its :8000
        # listener only on a fresh container's first boot (/var/lib/unit empty);
        # a restart skips it and leaves `listeners: {}`, so nothing serves.
        # up_services already brought web up cleanly — just wait for it to serve.
        # Django is a heavy import; first health can take ~7 min.
        timing.stage("health poll start")
        self.backend.wait_http_ok("/_health", expect=200, timeout=900)
        timing.stage("health poll pass")

    def deep_health(self) -> None:
        # /_health is UNAUTHENTICATED — it passed the whole time previews were
        # 500ing on /api/projects/@current/ (the personhog drift), so "healthy"
        # meant "process is up", not "app is usable". This gate logs into the
        # seeded demo user and hits the endpoints that actually broke, so a
        # regression like that fails the bring-up instead of shipping a dead box.
        #
        # Skipped on --no-seed: no seed means no demo user to log in as. The CI
        # path always seeds and the golden is pre-seeded, so in practice the
        # probes run; but if seeding was skipped, note it and move on rather than
        # fail on a login that can't succeed.
        if not self.seed_demo_data:
            sys.stderr.write("[hogbox-preview] deep health skipped: --no-seed leaves no demo user to authenticate as\n")
            return
        timing.stage("deep health (authed api)")
        self._run_authed_probe()

    def _run_authed_probe(self) -> None:
        # Everything runs INSIDE the box (curl against localhost:8000), so it's
        # independent of external networking — same posture as wait_http_ok. One
        # bash script does the whole login+probe flow with a shared cookie jar:
        #   1. GET  /login          -> seed the CSRF cookie
        #   2. POST /api/login/     -> authenticate the demo user
        #   3. GET  /api/projects/@current/               expect 200
        #   4. POST /api/environments/@current/query/     expect 200 (HogQL)
        # It prints "STEP <name> <http_code>" per step and the body of the first
        # non-2xx, so the Python side can raise with the exact failure.
        base = f"http://localhost:{self.backend.web_port}"
        script = f"""
set -u
jar=$(mktemp)
probe() {{ # name method path [json]
  name=$1; method=$2; path=$3; data=${{4:-}}
  if [ -n "$data" ]; then
    csrf=$(awk '/csrftoken/ {{print $7}}' "$jar" | tail -n1)
    code=$(curl -s -o /tmp/dh_body -w '%{{http_code}}' -m 30 -b "$jar" -c "$jar" \
      -X "$method" -H 'Content-Type: application/json' -H "X-CSRFToken: $csrf" \
      -H 'Referer: {base}/' -d "$data" "{base}$path")
  else
    code=$(curl -s -o /tmp/dh_body -w '%{{http_code}}' -m 30 -b "$jar" -c "$jar" "{base}$path")
  fi
  echo "STEP $name $code"
  case "$code" in 2*) ;; *) echo "BODY_START"; head -c 300 /tmp/dh_body; echo; echo "BODY_END"; return 1;; esac
}}
probe login GET /login || exit 1
probe api_login POST /api/login/ '{{"email":"{_DEMO_EMAIL}","password":"{_DEMO_PASSWORD}"}}' || exit 1
probe projects GET /api/projects/@current/ || exit 1
probe hogql POST /api/environments/@current/query/ '{{"query":{{"kind":"HogQLQuery","query":"select 1"}}}}' || exit 1
echo "DEEP_HEALTH_OK"
"""
        r = self.backend.exec(script, timeout=180)
        if "DEEP_HEALTH_OK" in r.stdout:
            timing.stage("deep health pass")
            return
        # Failed: surface the step + status + body, and the web log tail. The
        # missing traceback is what cost hours on 2026-07-06 — dump it here so
        # CI shows the Django error directly instead of just "not 200".
        logs = self.backend.exec("docker logs --tail 40 posthog-web-1 2>&1", timeout=60)
        raise RuntimeError(
            "deep health (authed api) failed — the app is up but not usable:\n"
            f"{r.stdout.strip()}\n{r.stderr.strip()}\n"
            f"--- docker logs --tail 40 posthog-web-1 ---\n{logs.stdout.strip()}"
        )

    # --- internal ------------------------------------------------------------
    def _compose(self, args: str) -> str:
        return f"cd {self.repo_dir} && docker compose -f {self.COMPOSE} -f {self.OVERRIDE} {args}"
