"""Hogland preview layer: restore a warmed golden snapshot into a hogbox
(Firecracker microVM), expose the web port at the box's tailnet edge URL
(``https://<box>.boxes.hogland.<env>.posthog.dev/``), and reach it over ssh
with the golden's baked seed key.

Provisioning goes through the ``hogland`` CLI (it knows ``--web-port`` ->
BoxSpec.Expose; the generated Python SDK doesn't surface that field yet). The
data plane (exec/write_file) is plain ssh via ``SSHBackend``.
"""

from __future__ import annotations

import json
import subprocess

from .backend import SSHBackend, SSHTarget


class HoglandBackend(SSHBackend):
    def __init__(
        self,
        *,
        host: str,
        snapshot: str = "alias:devbox-golden",
        cpus: int = 16,
        memory_mib: int = 65536,
        disk_gib: int = 100,
        web_port: int = 8000,
        ssh_user: str = "hog",
        ssh_key: str | None = None,
        cli: str = "hogland",
        name: str = "posthog-preview",
        box_id: str | None = None,
    ):
        super().__init__(web_port=web_port)
        self.host = host
        self.snapshot = snapshot
        # The golden is pinned to this sizing; restore must match it exactly
        # (the "omit to inherit" path is broken server-side — see NOTES).
        self.cpus = cpus
        self.memory_mib = memory_mib
        self.disk_gib = disk_gib
        self.ssh_user = ssh_user
        self.ssh_key = ssh_key
        self.cli = cli
        self.name = name
        self._box_id = box_id
        self._view: dict | None = None

    # --- control plane: the `hogland` CLI ------------------------------------
    def _cli(self, *args: str, timeout: int = 600) -> str:
        argv = [self.cli, "--host", self.host, *args]
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise RuntimeError(f"`{' '.join(argv)}` failed: {p.stderr.strip() or p.stdout.strip()}")
        return p.stdout

    def provision(self) -> None:
        if self._box_id:  # reuse an existing box
            self._view = json.loads(self._cli("box", "get", self._box_id))
            return
        out = self._cli(
            "box",
            "create",
            "--snapshot-id",
            self.snapshot,
            "--cpus",
            str(self.cpus),
            "--memory-mib",
            str(self.memory_mib),
            "--disk-gib",
            str(self.disk_gib),
            "--web-port",
            str(self.web_port),
            "--name",
            self.name,
            "--timeout",
            "10m",
        )
        # `box create` waits until running and prints the final box JSON.
        self._view = json.loads(out)
        self._box_id = self._view["id"]

    def _require_view(self) -> dict:
        if self._view is None:
            raise RuntimeError("provision() must run before the box is usable")
        return self._view

    def ssh_target(self) -> SSHTarget:
        v = self._require_view()
        return SSHTarget(
            host=v["public_ip"],
            port=v["guest_ssh_port"],
            user=self.ssh_user,
            key_path=self.ssh_key,
        )

    @property
    def web_url(self) -> str:
        url = self._require_view().get("web_url")
        if not url:
            raise RuntimeError(
                "box has no web_url — the box edge isn't configured in this env, "
                "or the box wasn't created with --web-port"
            )
        return url.rstrip("/")

    @property
    def box_id(self) -> str | None:
        return self._box_id

    def destroy(self) -> None:
        if self._box_id:
            self._cli("box", "delete", self._box_id, timeout=120)
