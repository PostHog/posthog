"""Bake the hogland golden snapshot for task sandboxes.

Boots a hogbox, replays ``Dockerfile.sandbox-base``'s steps over exec/write_file,
snapshots the box, and points a global alias (default ``posthog-tasks-default``)
at the result. ``HoglandSandbox.create`` restores every task sandbox from that
alias, so re-running this command against a cluster is the hogland equivalent of
publishing a new base image tag.

The box is baked with the exact machine shape ``SandboxConfig`` defaults to
(4 CPU / 16 GiB / 64 GiB): hogland snapshot restores must inherit-or-match the
snapshot's spec, so the golden spec IS the task sandbox spec.

Keep the steps in sync with
``products/tasks/backend/sandbox/images/Dockerfile.sandbox-base`` — that file
remains the source of truth for what a task sandbox contains.
"""

import io
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import httpx
from hogland import Hogbox, Hogland

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.hogland_sandbox import (
    HOGLAND_GOLDEN_CPU_CORES,
    HOGLAND_GOLDEN_DISK_GB,
    HOGLAND_GOLDEN_MEMORY_GB,
    get_hogland_api_token,
)
from products.tasks.backend.logic.services.local_skills import LocalSkillsCache, populate_skills_directory

SANDBOX_IMAGES_DIR = Path("products/tasks/backend/sandbox/images")

# Pins mirrored from Dockerfile.sandbox-base ARGs.
UV_VERSION = "0.11.15"
GIT_VERSION = "2.49.1"
GIT_SHA256 = "310831de967f1c8c5e8ff55f92807dea89f83dc3d3d2a5d16c209bd01a31def1"
RUFF_VERSION = "0.14.11"
TY_VERSION = "0.0.29"
GH_CLI_VERSION = "2.97.0"
AGENTSH_TAG = "v0.18.3"
AGENTSH_SHA256_AMD64 = "4ac486eea1e10600c29078a7a992d2067774edfb66be1318a2acf1fcf8b6d774"
AGENTSH_SHA256_ARM64 = "d1393a27943d207442ea077b1d36d9561a8af5613e7b67d9f7d4fafd00626c6b"
RTK_VERSION = "0.43.0"
RTK_SHA256_AMD64 = "ff8a1e7766496e175291a85aeca1dc97c9ff6df33e51e5893d1fbc78fea2a609"
RTK_SHA256_ARM64 = "5519f7ca12e5c143a609f0d28a0a77b97413a8dce31c2681f1a41c24519a8731"

APT_PACKAGES = (
    "curl wget git vim nano tree htop unzip zip jq "
    "build-essential pkg-config musl "
    "python3 python3-pip python3-venv python3-dev "
    "sqlite3 postgresql-client mysql-client redis-tools "
    "libssl-dev libcurl4-gnutls-dev libexpat1-dev libffi-dev libbz2-dev "
    "libreadline-dev libsqlite3-dev libncursesw5-dev xz-utils tk-dev "
    "libxml2-dev libxmlsec1-dev zlib1g-dev "
    "ca-certificates gnupg sudo"
)

# Dockerfile ENVs, made visible to every exec/SSH process in the box. /etc/environment
# covers PAM sessions; the systemd drop-in covers hog-exec (systemd services do not
# read /etc/environment), and its EnvironmentFile line is what lets the per-box
# `create(env=...)` values (materialised at /etc/hogbox-env) reach exec processes.
STATIC_ENV = {
    "DEBIAN_FRONTEND": "noninteractive",
    "TZ": "UTC",
    "GH_TELEMETRY": "false",
    "AGENTSH_SERVER": "http://127.0.0.1:18080",
    "IS_SANDBOX": "1",
    "PYTHONPATH": "/tmp/workspace",
    "PATH": "/opt/posthog/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}

EXEC_ENV_DROPIN = "\n".join(
    [
        "[Service]",
        *[f'Environment="{key}={value}"' for key, value in STATIC_ENV.items()],
        "EnvironmentFile=-/etc/hogbox-env",
        "",
    ]
)


# kw_only off so the ordered step list below stays readable as positional entries.
@frozen(kw_only=False)
class _BakeStep:
    label: str
    script: str
    timeout_seconds: int


def _bake_steps(agent_version: str) -> list[_BakeStep]:
    """The ordered shell steps that reconstruct Dockerfile.sandbox-base in a box."""
    return [
        _BakeStep(
            "apt packages",
            f"export DEBIAN_FRONTEND=noninteractive && apt-get update && "
            f"apt-get install -y --no-install-recommends {APT_PACKAGES} && rm -rf /var/lib/apt/lists/*",
            15 * 60,
        ),
        _BakeStep(
            f"git {GIT_VERSION} from source",
            "set -eux; "
            f'curl -fsSL -o /tmp/git.tar.xz "https://www.kernel.org/pub/software/scm/git/git-{GIT_VERSION}.tar.xz"; '
            f'echo "{GIT_SHA256}  /tmp/git.tar.xz" | sha256sum -c -; '
            "mkdir /tmp/git; tar -xf /tmp/git.tar.xz -C /tmp/git --strip-components=1; "
            'make -C /tmp/git prefix=/usr NO_GETTEXT=YesPlease NO_TCLTK=YesPlease -j"$(nproc)" all; '
            "make -C /tmp/git prefix=/usr NO_GETTEXT=YesPlease NO_TCLTK=YesPlease install; "
            "rm -rf /tmp/git /tmp/git.tar.xz; git --version; "
            "git help -a | grep -q '[[:space:]]backfill'",
            25 * 60,
        ),
        _BakeStep(
            "node 24",
            "curl -fsSL https://deb.nodesource.com/setup_24.x | bash - && "
            "apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/*",
            10 * 60,
        ),
        _BakeStep("npm globals", "npm install -g yarn pnpm typescript ts-node nodemon", 10 * 60),
        _BakeStep(
            "uv + ruff + ty",
            # The Dockerfile takes uv from its pinned official image; without a container
            # runtime we pin the same version's release tarball and verify it against the
            # checksum published with that release.
            "set -eux; "
            'arch="$(uname -m)"; '
            f'asset="uv-${{arch}}-unknown-linux-gnu.tar.gz"; '
            f'base="https://github.com/astral-sh/uv/releases/download/{UV_VERSION}"; '
            'curl -fsSL -o /tmp/uv.tar.gz "${base}/${asset}"; '
            'curl -fsSL -o /tmp/uv.tar.gz.sha256 "${base}/${asset}.sha256"; '
            'cd /tmp && echo "$(cut -d" " -f1 uv.tar.gz.sha256)  uv.tar.gz" | sha256sum -c -; '
            "tar -xzf /tmp/uv.tar.gz -C /tmp; "
            'install -m 755 "/tmp/uv-${arch}-unknown-linux-gnu/uv" "/tmp/uv-${arch}-unknown-linux-gnu/uvx" /usr/local/bin/; '
            'rm -rf /tmp/uv.tar.gz /tmp/uv.tar.gz.sha256 "/tmp/uv-${arch}-unknown-linux-gnu"; '
            f'UV_TOOL_BIN_DIR=/usr/local/bin uv tool install "ruff=={RUFF_VERSION}"; '
            f'UV_TOOL_BIN_DIR=/usr/local/bin uv tool install "ty=={TY_VERSION}"; '
            "ruff --version; ty --version",
            10 * 60,
        ),
        _BakeStep(
            f"gh CLI {GH_CLI_VERSION}",
            "set -eux; "
            'arch="$(dpkg --print-architecture)"; '
            "curl -fsSL -o /tmp/gh.deb "
            f'"https://github.com/cli/cli/releases/download/v{GH_CLI_VERSION}/gh_{GH_CLI_VERSION}_linux_${{arch}}.deb"; '
            "dpkg -i /tmp/gh.deb && rm /tmp/gh.deb",
            5 * 60,
        ),
        _BakeStep(
            f"agentsh {AGENTSH_TAG}",
            "set -eux; "
            f'version="{AGENTSH_TAG.removeprefix("v")}"; '
            'arch="$(dpkg --print-architecture)"; '
            'case "$arch" in '
            f'amd64) agentsh_sha256="{AGENTSH_SHA256_AMD64}" ;; '
            f'arm64) agentsh_sha256="{AGENTSH_SHA256_ARM64}" ;; '
            '*) echo "Unsupported architecture for agentsh: $arch" >&2; exit 1 ;; esac; '
            "curl -fsSL -o /tmp/agentsh.deb "
            f'"https://github.com/canyonroad/agentsh/releases/download/{AGENTSH_TAG}/agentsh_${{version}}_linux_${{arch}}.deb"; '
            'echo "${agentsh_sha256}  /tmp/agentsh.deb" | sha256sum -c -; '
            "dpkg -i /tmp/agentsh.deb && rm /tmp/agentsh.deb && agentsh --version; "
            "mkdir -p /var/lib/agentsh/sessions /var/lib/agentsh/quarantine /var/log/agentsh; "
            "chmod 777 /var/lib/agentsh /var/lib/agentsh/sessions /var/lib/agentsh/quarantine /var/log/agentsh",
            5 * 60,
        ),
        _BakeStep(
            f"rtk {RTK_VERSION}",
            "set -eux; "
            'arch="$(dpkg --print-architecture)"; '
            'case "$arch" in '
            f'amd64) rtk_asset="rtk-x86_64-unknown-linux-musl.tar.gz"; rtk_sha256="{RTK_SHA256_AMD64}" ;; '
            f'arm64) rtk_asset="rtk-aarch64-unknown-linux-gnu.tar.gz"; rtk_sha256="{RTK_SHA256_ARM64}" ;; '
            '*) echo "Unsupported architecture for rtk: $arch" >&2; exit 1 ;; esac; '
            "curl -fsSL -o /tmp/rtk.tar.gz "
            f'"https://github.com/rtk-ai/rtk/releases/download/v{RTK_VERSION}/${{rtk_asset}}"; '
            'echo "${rtk_sha256}  /tmp/rtk.tar.gz" | sha256sum -c -; '
            "tar -xzf /tmp/rtk.tar.gz -C /usr/local/bin rtk && rm /tmp/rtk.tar.gz && rtk --version",
            5 * 60,
        ),
        _BakeStep(
            f"@posthog/agent@{agent_version} in /scripts",
            "set -eux; mkdir -p /scripts && cd /scripts && npm init -y && "
            f'npm install "@posthog/agent@{agent_version}" && '
            "test -x /scripts/node_modules/.bin/agent-server",
            15 * 60,
        ),
        _BakeStep(
            "skills install",
            "set -eux; chmod +x /tmp/install-skills.sh; mkdir -p /tmp/skills; "
            "tar -xzf /tmp/skills.tar.gz -C /tmp/skills; "
            "/tmp/install-skills.sh /tmp/skills; rm -rf /tmp/install-skills.sh /tmp/skills /tmp/skills.tar.gz",
            5 * 60,
        ),
        _BakeStep(
            "git identity + guards + workspace",
            "set -eux; "
            'git config --global user.email "code@posthog.com"; '
            'git config --global user.name "PostHog Desktop"; '
            "chmod +x /opt/posthog/bin/git /opt/posthog/bin/gh /usr/local/bin/posthog-cpu-billing-sampler; "
            "mkdir -p /tmp/workspace",
            60,
        ),
        _BakeStep(
            "exec-daemon env wiring",
            # Make STATIC_ENV plus the per-box /etc/hogbox-env visible to hog-exec's
            # children — this is what gives exec processes the Modal-style container env.
            "set -eux; "
            # The guest image ships exactly one agent unit; target it directly and confirm
            # it is up. Grepping list-units yielded an empty match that aborted under set -e.
            "unit=hogpanion.service; "
            'systemctl is-active "$unit"; '
            'mkdir -p "/etc/systemd/system/${unit}.d"; '
            'cp /tmp/posthog-env.conf "/etc/systemd/system/${unit}.d/posthog-env.conf"; '
            "rm /tmp/posthog-env.conf; systemctl daemon-reload; "
            # A direct restart self-kills: this exec runs inside hogpanion's own
            # control-group cgroup, so the restart SIGTERMs bash, the exec, and
            # hogpanion together and the step never returns 0. Detach the restart
            # into a transient unit that fires after this exec exits; the next step
            # confirms the service came back.
            'systemd-run --collect --unit=hogpanion-reload --on-active=2 systemctl restart "$unit"',
            120,
        ),
        _BakeStep(
            "confirm hogpanion reload",
            "set -eux; unit=hogpanion.service; "
            # Give the deferred restart time to fire, so we do not confirm the
            # pre-restart instance, then poll until the service is active.
            "sleep 3; "
            "for _ in $(seq 1 60); do "
            'if systemctl is-active --quiet "$unit"; then exit 0; fi; '
            "sleep 1; done; "
            'echo "hogpanion.service did not become active after reload" >&2; '
            'systemctl status "$unit" --no-pager || true; exit 1',
            120,
        ),
        _BakeStep(
            "verify",
            "set -eux; python3 --version; node --version; npm --version; "
            "gh --version; rtk --version; agentsh --version; "
            "test -x /scripts/node_modules/.bin/agent-server; "
            "test -x /opt/posthog/bin/git; test -x /opt/posthog/bin/gh",
            5 * 60,
        ),
    ]


class Command(BaseCommand):
    help = "Bake the hogland golden snapshot for task sandboxes and point the alias at it"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--host", default=None, help="Hogland API URL (default: settings.HOGLAND_API_URL)")
        parser.add_argument("--token", default=None, help="Hogland API token (default: settings.HOGLAND_API_TOKEN)")
        parser.add_argument("--alias", default="posthog-tasks-default", help="Snapshot alias to (re)point")
        parser.add_argument("--agent-version", default="latest", help="@posthog/agent version to install")
        parser.add_argument(
            "--keep-box", action="store_true", help="Keep the bake box running afterwards for inspection"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        host = options["host"] or settings.HOGLAND_API_URL
        # Prefer the projected token file over the static token, matching the runtime
        # client, so a rebake works in a production-shaped environment.
        token = options["token"] or get_hogland_api_token()
        if not host or not token:
            raise CommandError("Pass --host/--token or set HOGLAND_API_URL/HOGLAND_API_TOKEN")

        skills_payload = self._build_skills_tarball()

        client = Hogland(token=token, base_url=host, timeout=httpx.Timeout(30 * 60, connect=15))
        self.stdout.write(f"Booting bake box on {host}...")
        box = client.create(
            # The golden shape every hogland task box inherits on restore.
            cpus=HOGLAND_GOLDEN_CPU_CORES,
            memory_mib=int(HOGLAND_GOLDEN_MEMORY_GB * 1024),
            disk_gib=int(HOGLAND_GOLDEN_DISK_GB),
            name="posthog-tasks-bake",
            kind="posthog-tasks-bake",
            ttl_seconds=3600,
        )
        self.stdout.write(f"Box {box.id} running")

        try:
            self._upload_inputs(box, skills_payload)
            for step in _bake_steps(options["agent_version"]):
                self.stdout.write(f"--> {step.label}")
                result = box.exec(["bash", "-c", step.script], timeout_seconds=step.timeout_seconds)
                if result.exit_code != 0:
                    self.stderr.write(result.stdout[-4000:])
                    self.stderr.write(result.stderr[-4000:])
                    raise CommandError(f"Bake step failed: {step.label} (exit {result.exit_code})")

            self.stdout.write("Snapshotting (pause -> dump -> resume)...")
            record = box.snapshot()
            self.stdout.write(f"Snapshot {record.id} ({record.size_bytes} bytes, pause {record.pause_ms}ms)")

            self._point_alias(host, token, record.id, options["alias"])
            self.stdout.write(self.style.SUCCESS(f"Alias {options['alias']} -> {record.id}"))
        finally:
            if options["keep_box"]:
                self.stdout.write(f"Keeping bake box {box.id} (--keep-box); it expires with its 1h TTL")
            else:
                box.delete()
                self.stdout.write(f"Deleted bake box {box.id}")

    def _build_skills_tarball(self) -> bytes:
        """Tar the locally built skills (same content the Dockerfile COPYs from CD)."""
        base_dir = Path(settings.BASE_DIR)
        with tempfile.TemporaryDirectory(prefix="hogland-skills-") as tmp:
            skills_dir = Path(tmp) / "skills"
            LocalSkillsCache(base_dir).ensure_built()
            populate_skills_directory(skills_dir, base_dir=base_dir)
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
                for child in sorted(skills_dir.iterdir()):
                    tar.add(child, arcname=child.name)
            payload = buffer.getvalue()
        if len(payload) > 60 * 1024 * 1024:
            raise CommandError(f"Skills tarball is {len(payload)} bytes; hogland write_file caps at 64 MiB")
        self.stdout.write(f"Skills tarball: {len(payload)} bytes")
        return payload

    def _upload_inputs(self, box: Hogbox, skills_payload: bytes) -> None:
        images_dir = Path(settings.BASE_DIR) / SANDBOX_IMAGES_DIR
        uploads = {
            "/tmp/skills.tar.gz": skills_payload,
            "/tmp/install-skills.sh": (images_dir / "install-skills.sh").read_bytes(),
            "/opt/posthog/bin/git": (images_dir / "git-guard.sh").read_bytes(),
            "/opt/posthog/bin/gh": (images_dir / "gh-guard.sh").read_bytes(),
            "/usr/local/bin/posthog-cpu-billing-sampler": (images_dir / "cpu_billing_sampler.py").read_bytes(),
            "/etc/environment": ("\n".join(f'{k}="{v}"' for k, v in STATIC_ENV.items()) + "\n").encode(),
            "/tmp/posthog-env.conf": EXEC_ENV_DROPIN.encode(),
        }
        for path, payload in uploads.items():
            box.write_file(path, payload, mkdir=True)
            self.stdout.write(f"Uploaded {path} ({len(payload)} bytes)")

    def _point_alias(self, host: str, token: str, snapshot_id: str, alias: str) -> None:
        # The SDK has no alias methods yet; the endpoint is
        # PUT /v1/snapshots/{id}/aliases/{alias} (owner-only, idempotent re-point).
        response = httpx.put(
            f"{host.rstrip('/')}/v1/snapshots/{snapshot_id}/aliases/{alias}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.status_code >= 400:
            raise CommandError(f"Alias update failed: {response.status_code} {response.text[:500]}")
