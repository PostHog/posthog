"""The *previous* preview layer, kept as a skeleton to prove the seam.

Before hogland, previews ran on DigitalOcean droplets (see ``bin/hobby-ci.py``
for the full droplet + DNS + cloud-init logic). Porting that here means
filling in ``provision`` / ``destroy`` and pointing ``ssh_target`` / ``web_url``
at the droplet — the PostHog stack recipe in ``stack.py`` runs unchanged. This
stub is intentionally not wired up; it exists so the layer boundary is concrete
and the next swap has an obvious shape to follow.
"""

from __future__ import annotations

from .backend import SSHBackend, SSHTarget


class DigitalOceanBackend(SSHBackend):
    def __init__(self, *, domain: str, ip: str | None = None, ssh_key: str | None = None, web_port: int = 8000):
        super().__init__(web_port=web_port)
        self.domain = domain
        self._ip = ip
        self.ssh_key = ssh_key

    def provision(self) -> None:
        # Port bin/hobby-ci.py: create the droplet, attach the DNS record,
        # wait for cloud-init, install docker + the repo, expose web_port.
        raise NotImplementedError("DigitalOcean provisioning lives in bin/hobby-ci.py; port it here when needed")

    def ssh_target(self) -> SSHTarget:
        if not self._ip:
            raise RuntimeError("no droplet IP — provision() first")
        return SSHTarget(host=self._ip, port=22, user="root", key_path=self.ssh_key)

    @property
    def web_url(self) -> str:
        return f"https://{self.domain}".rstrip("/")

    def destroy(self) -> None:
        raise NotImplementedError("port droplet teardown from bin/hobby-ci.py")
