from __future__ import annotations

import re
import json
from ipaddress import IPv4Address
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import uuid4

from django.conf import settings

import modal
from modal.stream_type import StreamType

from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
from products.tasks.backend.logic.services.sandbox import (
    SandboxConfig,
    SandboxTemplate,
    get_sandbox_class_for_run_backend,
)

if TYPE_CHECKING:
    from modal.sandbox import SidecarContainer


CAPABILITY_PATH = "/run/posthog/egress-capability"
RELAY_NAME = "egress-relay"

_PROBE = """
import concurrent.futures, http.client, json, sys
from collections import Counter
from pathlib import Path
def request(_):
    connection = http.client.HTTPConnection("egress-relay", 8080, timeout=10)
    try:
        token = Path("/run/posthog/egress-capability").read_text()
        connection.request("GET", "/v1/probe", headers={"Authorization": "Bearer " + token})
        response = connection.getresponse()
        response.read(1024)
        return response.status
    except (OSError, http.client.HTTPException):
        return 0
    finally:
        connection.close()
with concurrent.futures.ThreadPoolExecutor(max_workers=int(sys.argv[2])) as executor:
    print(json.dumps(dict(Counter(executor.map(request, range(int(sys.argv[1])))))))
"""

_WAIT_READY = """
import time, urllib.request
for _ in range(60):
    try:
        with urllib.request.urlopen("http://127.0.0.1:9090/readyz", timeout=1) as response:
            if response.status == 204:
                break
    except OSError:
        pass
    time.sleep(.2)
else:
    raise SystemExit(1)
"""


class ModalEgressProbe:
    def __init__(self, sandbox: ModalSandbox, sidecar: SidecarContainer, endpoint: str, ttl_seconds: int) -> None:
        self.sandbox = sandbox
        self.sidecar = sidecar
        self.endpoint = endpoint
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _execute(container: modal.Sandbox | SidecarContainer, *args: str, timeout: int = 30) -> str:
        process = container.exec(*args, timeout=timeout, stderr=StreamType.DEVNULL)
        output = process.stdout.read()
        process.wait()
        if process.returncode:
            raise RuntimeError("Egress probe control command failed")
        return output

    @classmethod
    def create(
        cls,
        *,
        name: str,
        relay_image_id: str,
        endpoint: str,
        ttl_seconds: int = 900,
        dev_proxy_ipv4: str | None = None,
    ) -> ModalEgressProbe:
        if not (settings.DEBUG or settings.TEST) or str(settings.SANDBOX_PROVIDER).upper() != "MODAL_DOCKER":
            raise RuntimeError("Egress probes require the local MODAL_DOCKER provider")
        target = urlsplit(endpoint)
        if (
            target.scheme != "https"
            or not target.hostname
            or target.netloc != target.netloc.lower()
            or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", target.hostname)
            or target.username is not None
            or target.password is not None
            or target.path not in ("", "/")
            or target.query
            or target.fragment
            or not 60 <= ttl_seconds <= 1800
        ):
            raise ValueError("Invalid egress probe endpoint or lifetime")
        target_port = target.port or 443
        if target_port != 443 and dev_proxy_ipv4 is None:
            raise ValueError("Domain-restricted egress requires port 443")
        proxy_ip = IPv4Address(dev_proxy_ipv4) if dev_proxy_ipv4 is not None else None
        if proxy_ip is not None and not proxy_ip.is_global:
            raise ValueError("The development proxy address must be a public IPv4 address")
        sandbox_class = get_sandbox_class_for_run_backend("modal")
        if not issubclass(sandbox_class, ModalSandbox):
            raise RuntimeError("Egress probes require Modal")
        sandbox = sandbox_class.create(
            SandboxConfig(
                name=name,
                template=SandboxTemplate.SLIM_BASE,
                vm_runtime=True,
                agent_egress_probe=True,
                memory_gb=2,
                cpu_cores=1,
                ttl_seconds=ttl_seconds,
                metadata={"purpose": "agent-egress-probe"},
            )
        )
        try:
            sidecar = sandbox._sandbox._experimental_sidecars.create(
                "sleep",
                "infinity",
                name=RELAY_NAME,
                image=modal.Image.from_id(relay_image_id),
                outbound_cidr_allowlist=[f"{proxy_ip}/32"] if proxy_ip else None,
                outbound_domain_allowlist=[target.hostname] if proxy_ip is None else None,
                experimental_memory_reserve_consume_mib=1024,
            )
            instance = cls(sandbox, sidecar, endpoint.rstrip("/"), ttl_seconds)
            instance._execute(sidecar, "mkdir", "-m", "0700", "-p", "/run/egress")
            if proxy_ip is not None:
                instance._execute(
                    sidecar,
                    "python3",
                    "-c",
                    "from pathlib import Path; import sys; p=Path('/etc/hosts'); "
                    "p.write_text(p.read_text()+'\\n'+sys.argv[1]+' '+sys.argv[2]+'\\n')",
                    str(proxy_ip),
                    target.hostname,
                )
            instance._execute(
                sidecar,
                "sh",
                "-c",
                "umask 077; exec openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 "
                "-out /run/egress/relay-key.pem",
            )
            instance._execute(
                sidecar,
                "openssl",
                "req",
                "-new",
                "-key",
                "/run/egress/relay-key.pem",
                "-out",
                "/run/egress/relay.csr",
                "-subj",
                "/CN=agent-egress-probe",
            )
            return instance
        except BaseException:
            sandbox.destroy()
            raise

    def certificate_request(self) -> str:
        return self.sidecar.filesystem.read_text("/run/egress/relay.csr")

    def start_relay(self, *, certificate: str, server_ca: str) -> None:
        self.sidecar.filesystem.write_text(certificate, "/run/egress/relay.pem")
        self.sidecar.filesystem.write_text(server_ca, "/run/egress/server-ca.pem")
        configuration = {
            "endpoint": self.endpoint,
            "listen_address": "0.0.0.0:8080",
            "admin_address": "127.0.0.1:9090",
            "certificate_file": "/run/egress/relay.pem",
            "private_key_file": "/run/egress/relay-key.pem",
            "server_ca_file": "/run/egress/server-ca.pem",
            "request_timeout_seconds": 20,
            "shutdown_timeout_seconds": 5,
        }
        self.sidecar.filesystem.write_text(json.dumps(configuration), "/run/egress/relay.json")
        self.sidecar.exec(
            "sh",
            "-c",
            "exec /usr/local/bin/egress-relay -config /run/egress/relay.json >/dev/null 2>/run/egress/relay.stderr",
            timeout=self.ttl_seconds,
            stdout=StreamType.DEVNULL,
            stderr=StreamType.DEVNULL,
        )
        self._execute(self.sidecar, "python3", "-c", _WAIT_READY, timeout=90)

    def publish_capability(self, token: str) -> None:
        guest = self.sandbox._sandbox
        self._execute(guest, "mkdir", "-m", "0700", "-p", "/run/posthog")
        temporary = f"{CAPABILITY_PATH}.{uuid4().hex}"
        guest.filesystem.write_text(token, temporary)
        self._execute(
            guest,
            "python3",
            "-c",
            "import os,sys; os.chmod(sys.argv[1],0o600); os.replace(sys.argv[1],sys.argv[2])",
            temporary,
            CAPABILITY_PATH,
        )

    def probe(self, *, count: int = 1, concurrency: int = 1) -> dict[int, int]:
        if not 1 <= count <= 1000 or not 1 <= concurrency <= 32:
            raise ValueError("Probe count must be 1 to 1000 and concurrency 1 to 32")
        output = self._execute(
            self.sandbox._sandbox, "python3", "-c", _PROBE, str(count), str(concurrency), timeout=120
        )
        try:
            result = json.loads(output)
        except ValueError:
            raise RuntimeError("Invalid egress probe response") from None
        if not isinstance(result, dict) or not all(
            isinstance(status, str)
            and status.isascii()
            and status.isdecimal()
            and str(int(status)) == status
            and (int(status) == 0 or 100 <= int(status) <= 599)
            and type(total) is int
            and total > 0
            for status, total in result.items()
        ):
            raise RuntimeError("Invalid egress probe response")
        if sum(result.values()) != count:
            raise RuntimeError("Incomplete egress probe response")
        return {int(status): total for status, total in result.items()}

    def close(self) -> None:
        self.sandbox.destroy()
