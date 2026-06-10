"""Hogland preview layer, driven by the ``posthog-hogland`` SDK.

Restore a warmed golden snapshot into a hogbox (Firecracker microVM), run the
stack inside it, and reach its web over hogplane's authenticated proxy.

Why the SDK and not the ``hogland`` CLI: the SDK is the whole PreviewBackend
surface, keyless, with one ``pip install``. ``client.create(snapshot_id=...)``
restores; ``box.exec`` / ``box.write_file`` run commands and write files over
hogplane's HTTP API (no SSH); ``box.destroy`` tears down. CI already proves this
path (``bin/hogbox-ci.py``). The CLI route meant shipping a private-repo binary
to the runner plus an SSH-key secret for exec — neither is needed.

The box's web is reached via ``box.proxy_url(web_port)`` — an authenticated
hogplane URL (tailnet creds, nothing public). Note it's *path-prefixed*
(``/v1/hogboxes/<id>/proxy/<port>/``), not the box-front subdomain: the SDK
0.1.0 ``create`` doesn't surface the ``Expose`` spec. Fine for a tailnet-only
preview; a clean per-box subdomain is a later SDK addition (mirror ``--web-port``).
"""

from __future__ import annotations

import pathlib
import tempfile
import subprocess

from hogland import AccessType, Hogland

from .backend import ExecResult, PreviewBackend


def _ephemeral_ssh_pubkey() -> str:
    """A throwaway ed25519 public key.

    ``access_type=ssh_public`` still requires *a* key at restore time, but
    exec/write_file go over the HTTP API, so this key never reaches the box.
    Drop once hogland ships a keyless access type.
    """
    with tempfile.TemporaryDirectory() as d:
        key = pathlib.Path(d) / "id_ed25519"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-q", "-C", "hogbox-preview", "-f", str(key)],
            check=True,
        )
        return key.with_suffix(".pub").read_text().strip()


class HoglandBackend(PreviewBackend):
    def __init__(
        self,
        *,
        host: str | None = None,
        snapshot: str = "alias:posthog-preview-golden",
        cpus: float = 8,
        memory_mib: int = 16384,
        disk_gib: int = 100,
        disk_class: str = "mirrored",
        web_port: int = 8000,
        name: str = "posthog-preview",
        kind: str = "sandbox",
        ttl_seconds: int | None = None,
        box_id: str | None = None,
        token: str | None = None,
    ):
        super().__init__(web_port=web_port)
        # Hogland() reads HOG_TOKEN / HOG_HOST from env; --host/--token override.
        self._client = Hogland(token=token, base_url=host)
        self.snapshot = snapshot
        # The golden is pinned to this sizing; restore must MATCH it exactly
        # ("omit to inherit" is unreliable server-side).
        self.cpus = cpus
        self.memory_mib = memory_mib
        self.disk_gib = disk_gib
        self.disk_class = disk_class
        self.name = name
        self.kind = kind
        self.ttl_seconds = ttl_seconds
        self._box_id = box_id
        self._box = None  # hogland.Hogbox once provisioned

    # --- layer methods -------------------------------------------------------
    def provision(self) -> None:
        if self._box is not None:
            return
        if self._box_id:  # reuse an existing box
            self._box = self._client.get(self._box_id)
        else:
            self._box = self._client.create(
                snapshot_id=self.snapshot,
                cpus=self.cpus,
                memory_mib=self.memory_mib,
                disk_gib=self.disk_gib,
                disk_class=self.disk_class,
                access_type=AccessType.ssh_public,
                ssh_public_key=_ephemeral_ssh_pubkey(),
                name=self.name,
                kind=self.kind,
                ttl_seconds=self.ttl_seconds,
            )
            self._box_id = self._box.id
        # `running` means the VM resumed, not that hogpanion's HTTP API answers
        # yet — a restored box needs a beat before the first exec.
        self._wait_exec_ready()

    def exec(self, command: str, *, timeout: int = 120) -> ExecResult:
        r = self._require_box().exec(["bash", "-lc", command], timeout_seconds=timeout)
        return ExecResult(r.exit_code, r.stdout, r.stderr)

    def write_file(self, remote_path: str, content: str) -> None:
        self._require_box().write_file(remote_path, content.encode(), mkdir=True)

    @property
    def web_url(self) -> str:
        # Authenticated hogplane proxy into the in-guest web port. Path-prefixed
        # (see module docstring); the in-box /_health probe is unaffected.
        return self._require_box().proxy_url(self.web_port).rstrip("/")

    @property
    def box_id(self) -> str | None:
        return self._box_id

    def destroy(self) -> None:
        box = self._resolve_box()
        if box is not None:
            box.destroy()

    # --- internal ------------------------------------------------------------
    def _require_box(self):
        if self._box is None:
            raise RuntimeError("provision() must run before the box is usable")
        return self._box

    def _resolve_box(self):
        """Find the box to destroy: the live handle, an explicit id, or — for CI
        cleanup that only knows the deterministic name — a name lookup."""
        if self._box is not None:
            return self._box
        if self._box_id:
            return self._client.get(self._box_id)
        if self.name:
            for v in self._client.iter_boxes():
                if getattr(v.spec, "name", None) == self.name:
                    return self._client.get(v.id)
        return None

    def _wait_exec_ready(self, *, timeout: int = 300, interval: int = 5) -> None:
        import time

        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            try:
                r = self._box.exec(["true"], timeout_seconds=20)
                if r.exit_code == 0:
                    return
                last = r.stderr or ""
            except Exception as e:  # noqa: BLE001 — keep polling through transient API errors
                last = str(e)
            time.sleep(interval)
        raise RuntimeError(f"box {self._box_id} exec API not ready within {timeout}s (last: {last})")
