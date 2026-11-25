from __future__ import annotations

import re
import json
from ipaddress import IPv4Address
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import uuid4

from django.conf import settings

import modal
from modal.exception import (
    Error as ModalError,
    NotFoundError,
    SandboxFilesystemNotFoundError,
)
from modal.stream_type import StreamType

from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
from products.tasks.backend.logic.services.sandbox import (
    SandboxConfig,
    SandboxTemplate,
    get_sandbox_class_for_run_backend,
)
from products.tasks.backend.logic.services.sandbox_config import (
    AGENT_EGRESS_DOMAIN_PATTERN,
    MAX_SANDBOX_TTL_SECONDS,
    agent_egress_enrollment_enabled,
    agent_egress_enrollment_environment,
    agent_egress_staging_environment,
    agent_egress_staging_probe_enabled,
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
    connection = http.client.HTTPConnection(sys.argv[3], 8080, timeout=10)
    try:
        token = Path(sys.argv[4]).read_text()
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
deadline = time.monotonic() + 20
while True:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SystemExit(1)
    try:
        with urllib.request.urlopen("http://127.0.0.1:9090/readyz", timeout=min(1, remaining)) as response:
            if response.status == 204:
                break
    except OSError:
        pass
    time.sleep(min(.2, max(0, deadline - time.monotonic())))
"""

_PREPARE_IDENTITY = """
import fcntl, os, subprocess, sys
from pathlib import Path
os.umask(0o077)
directory = Path(sys.argv[1])
directory.mkdir(mode=0o700, parents=True, exist_ok=True)
with (directory / "identity.lock").open("w") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    key = directory / "relay-key.pem"
    csr = directory / "relay.csr"
    for destination, command in (
        (key, ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048"]),
        (csr, ["openssl", "req", "-new", "-key", str(key), "-subj", "/CN=agent-egress-probe"]),
    ):
        if not destination.exists():
            temporary = destination.with_suffix(".tmp")
            subprocess.run(command + ["-out", str(temporary)], check=True, stderr=subprocess.DEVNULL)
            temporary.chmod(0o600)
            temporary.replace(destination)
"""

_START_RELAY = """
import fcntl, json, os, sys
from pathlib import Path
directory = Path(sys.argv[1])
lock = (directory / "relay.lock").open("w")
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(0)
os.set_inheritable(lock.fileno(), True)
identity = {
    "pid": os.getpid(),
    "start_time": Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19],
    "executable": str(Path(sys.argv[2]).resolve()),
}
temporary = directory / "relay-process.tmp"
temporary.write_text(json.dumps(identity))
temporary.replace(directory / "relay-process.json")
with (directory / "relay.stderr").open("a") as errors:
    os.dup2(errors.fileno(), 2)
os.execv(sys.argv[2], sys.argv[2:])
"""

_RELAY_RUNNING = """
import fcntl, sys
from pathlib import Path
with (Path(sys.argv[1]) / 'relay.lock').open('a') as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('running')
"""

_RENEW_CERTIFICATE = """
import fcntl, json, os, signal, sys, time, urllib.request
from pathlib import Path
directory, candidate = Path(sys.argv[1]), Path(sys.argv[2])
deadline = time.monotonic() + 4
def counters():
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Relay reload acknowledgement expired')
    with urllib.request.urlopen(sys.argv[3], timeout=min(.5, remaining)) as response:
        values = {}
        for line in response.read(65536).decode().splitlines():
            for outcome in ('success', 'failure'):
                prefix = 'egress_reload_total{outcome="' + outcome + '"} '
                if line.startswith(prefix):
                    values[outcome] = float(line[len(prefix):])
        return values
def verify_process(identity):
    process = Path('/proc') / str(identity['pid'])
    if (
        identity['pid'] <= 1
        or process.joinpath('stat').read_text().rsplit(')', 1)[1].split()[19] != identity['start_time']
        or str(process.joinpath('exe').resolve()) != identity['executable']
    ):
        raise RuntimeError('The relay process has changed')
try:
    with (directory / 'certificate.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        identity = json.loads((directory / 'relay-process.json').read_text())
        pidfd = os.pidfd_open(identity['pid'])
        try:
            verify_process(identity)
            before = counters()
            certificate = directory / 'relay.pem'
            previous = certificate.read_bytes()
            candidate.chmod(0o600)
            candidate.replace(certificate)
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGHUP)
                while True:
                    after = counters()
                    verify_process(identity)
                    if after.get('failure', 0) > before.get('failure', 0):
                        raise RuntimeError('The relay rejected its renewed certificate')
                    if after.get('success', 0) > before.get('success', 0):
                        break
                    time.sleep(min(.05, max(0, deadline - time.monotonic())))
            except BaseException:
                candidate.write_bytes(previous)
                candidate.chmod(0o600)
                candidate.replace(certificate)
                raise
        finally:
            os.close(pidfd)
finally:
    candidate.unlink(missing_ok=True)
"""


class AgentEgressCertificateDeliveryError(RuntimeError):
    pass


class ModalEgressProbe:
    def __init__(
        self,
        sandbox: ModalSandbox,
        sidecar: SidecarContainer,
        endpoint: str,
        ttl_seconds: int,
        relay_name: str = RELAY_NAME,
    ) -> None:
        self.sandbox = sandbox
        self.sidecar = sidecar
        self.endpoint = endpoint
        self.ttl_seconds = ttl_seconds
        self.relay_name = relay_name
        self.capability_path = CAPABILITY_PATH if relay_name == RELAY_NAME else f"{CAPABILITY_PATH}.{relay_name}"

    @staticmethod
    def _sandbox_class(*, cleanup: bool = False) -> type[ModalSandbox]:
        if (
            not ((settings.DEBUG or settings.TEST) and str(settings.SANDBOX_PROVIDER).upper() == "MODAL_DOCKER")
            and not agent_egress_staging_probe_enabled()
            and not agent_egress_enrollment_enabled()
            and not (cleanup and (agent_egress_staging_environment() or agent_egress_enrollment_environment()))
        ):
            raise RuntimeError("Egress probes require the local MODAL_DOCKER provider")
        sandbox_class = get_sandbox_class_for_run_backend("modal")
        if not issubclass(sandbox_class, ModalSandbox):
            raise RuntimeError("Egress probes require Modal")
        return sandbox_class

    @staticmethod
    def _execute(container: modal.Sandbox | SidecarContainer, *args: str, timeout: int = 30) -> str:
        process = container.exec(*args, timeout=timeout, stderr=StreamType.DEVNULL)
        output = process.stdout.read()
        process.wait()
        if process.returncode:
            raise RuntimeError("Egress probe control command failed")
        return output

    @staticmethod
    def _destination(
        endpoint: str, ttl_seconds: int, dev_proxy_ipv4: str | None, *, max_ttl_seconds: int = 1800
    ) -> tuple[str, IPv4Address | None]:
        target = urlsplit(endpoint)
        if (
            target.scheme != "https"
            or not target.hostname
            or target.netloc != target.netloc.lower()
            or len(target.hostname) > 253
            or not re.fullmatch(AGENT_EGRESS_DOMAIN_PATTERN, target.hostname)
            or target.username is not None
            or target.password is not None
            or target.path not in ("", "/")
            or target.query
            or target.fragment
            or not 60 <= ttl_seconds <= max_ttl_seconds
        ):
            raise ValueError("Invalid egress probe endpoint or lifetime")
        target_port = target.port or 443
        if target_port != 443 and dev_proxy_ipv4 is None:
            raise ValueError("Domain-restricted egress requires port 443")
        proxy_ip = IPv4Address(dev_proxy_ipv4) if dev_proxy_ipv4 is not None else None
        if proxy_ip is not None and not proxy_ip.is_global:
            raise ValueError("The development proxy address must be a public IPv4 address")
        return target.hostname, proxy_ip

    @classmethod
    def _prepare_sidecar(
        cls,
        sandbox: ModalSandbox,
        *,
        relay_name: str,
        relay_image_id: str,
        endpoint: str,
        ttl_seconds: int,
        hostname: str,
        proxy_ip: IPv4Address | None,
    ) -> ModalEgressProbe:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", relay_name):
            raise ValueError("Invalid egress relay name")
        try:
            sidecar = sandbox._sandbox._experimental_sidecars.get(name=relay_name, include_terminated=True)
        except NotFoundError:
            sidecar = sandbox._sandbox._experimental_sidecars.create(
                "sleep",
                "infinity",
                name=relay_name,
                image=modal.Image.from_id(relay_image_id),
                outbound_cidr_allowlist=[f"{proxy_ip}/32"] if proxy_ip else None,
                outbound_domain_allowlist=[hostname] if proxy_ip is None else None,
                experimental_memory_reserve_consume_mib=1024,
            )
        if sidecar.poll() is not None:
            raise ValueError("The egress relay has ended")
        instance = cls(sandbox, sidecar, endpoint.rstrip("/"), ttl_seconds, relay_name)
        instance._execute(sidecar, "python3", "-c", _PREPARE_IDENTITY, "/run/egress")
        if proxy_ip is not None:
            instance._execute(
                sidecar,
                "python3",
                "-c",
                "from pathlib import Path; import sys; p=Path('/etc/hosts'); "
                "entry=sys.argv[1]+' '+sys.argv[2]; content=p.read_text(); "
                "p.write_text(content+'\\n'+entry+'\\n') if entry not in content.splitlines() else None",
                str(proxy_ip),
                hostname,
            )
        return instance

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
        sandbox_class = cls._sandbox_class()
        hostname, proxy_ip = cls._destination(endpoint, ttl_seconds, dev_proxy_ipv4)
        config = SandboxConfig(
            name=name,
            template=SandboxTemplate.SLIM_BASE,
            vm_runtime=True,
            agent_egress_probe=True,
            memory_gb=2,
            cpu_cores=1,
            ttl_seconds=ttl_seconds,
            metadata={"purpose": "agent-egress-probe"},
        )
        try:
            existing = modal.Sandbox.from_name(sandbox_class.DEFAULT_APP_NAME, name, include_terminated=True)
        except NotFoundError:
            sandbox = sandbox_class.create(config)
        else:
            if existing.poll() is not None:
                raise ValueError("The egress sandbox has ended")
            sandbox = sandbox_class(existing, config)
        return cls._prepare_sidecar(
            sandbox,
            relay_name=RELAY_NAME,
            relay_image_id=relay_image_id,
            endpoint=endpoint,
            ttl_seconds=ttl_seconds,
            hostname=hostname,
            proxy_ip=proxy_ip,
        )

    @classmethod
    def attach(
        cls,
        *,
        sandbox_id: str,
        relay_name: str,
        relay_image_id: str,
        endpoint: str,
        ttl_seconds: int,
        dev_proxy_ipv4: str | None = None,
    ) -> ModalEgressProbe:
        sandbox_class = cls._sandbox_class()
        hostname, proxy_ip = cls._destination(
            endpoint, ttl_seconds, dev_proxy_ipv4, max_ttl_seconds=MAX_SANDBOX_TTL_SECONDS
        )
        raw = modal.Sandbox.from_id(sandbox_id)
        if raw.poll() is not None:
            raise ValueError("The egress sandbox has ended")
        return cls._prepare_sidecar(
            sandbox_class(raw, SandboxConfig(name=sandbox_id)),
            relay_name=relay_name,
            relay_image_id=relay_image_id,
            endpoint=endpoint,
            ttl_seconds=ttl_seconds,
            hostname=hostname,
            proxy_ip=proxy_ip,
        )

    def certificate_request(self) -> str:
        return self.sidecar.filesystem.read_text("/run/egress/relay.csr")

    @classmethod
    def connect(
        cls,
        *,
        sandbox_id: str,
        sidecar_id: str,
        endpoint: str,
        ttl_seconds: int,
        relay_name: str = RELAY_NAME,
    ) -> ModalEgressProbe:
        sandbox_class = cls._sandbox_class()
        try:
            raw = modal.Sandbox.from_id(sandbox_id)
            if raw.poll() is not None:
                raise ValueError("The egress sandbox has ended")
            sandbox = sandbox_class(raw, SandboxConfig(name=sandbox_id))
            sidecar = raw._experimental_sidecars.get(name=relay_name, include_terminated=True)
            if sidecar.object_id != sidecar_id or sidecar.poll() is not None:
                raise ValueError("The egress relay has ended or been replaced")
        except NotFoundError:
            raise ValueError("The egress sandbox or relay no longer exists") from None
        return cls(sandbox, sidecar, endpoint, ttl_seconds, relay_name)

    def start_relay(self, *, certificate: str, server_ca: str, client_ca: str | None = None) -> None:
        if (
            client_ca is not None
            and self._execute(self.sidecar, "python3", "-c", _RELAY_RUNNING, "/run/egress").strip()
        ):
            self.renew_certificate(certificate)
            return
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
        if client_ca is not None:
            self.sidecar.filesystem.write_text(client_ca, "/run/egress/enrollment-ca.pem")
            configuration["client_ca_file"] = "/run/egress/enrollment-ca.pem"
        self.sidecar.filesystem.write_text(json.dumps(configuration), "/run/egress/relay.json")
        self.sidecar.exec(
            "python3",
            "-c",
            _START_RELAY,
            "/run/egress",
            "/usr/local/bin/egress-relay",
            "-config",
            "/run/egress/relay.json",
            timeout=self.ttl_seconds,
            stdout=StreamType.DEVNULL,
            stderr=StreamType.DEVNULL,
        )
        self._execute(self.sidecar, "python3", "-c", _WAIT_READY, timeout=30)

    def renew_certificate(self, certificate: str) -> None:
        candidate = f"/run/egress/relay-{uuid4().hex}.pem"
        try:
            self.sidecar.filesystem.write_text(certificate, candidate)
            self._execute(
                self.sidecar,
                "python3",
                "-c",
                _RENEW_CERTIFICATE,
                "/run/egress",
                candidate,
                "http://127.0.0.1:9090/metrics",
                timeout=7,
            )
        except (OSError, RuntimeError, ModalError) as error:
            raise AgentEgressCertificateDeliveryError("Relay certificate delivery failed") from error

    def publish_capability(self, token: str) -> None:
        guest = self.sandbox._sandbox
        self._execute(guest, "mkdir", "-m", "0700", "-p", "/run/posthog")
        temporary = f"{self.capability_path}.{uuid4().hex}"
        guest.filesystem.write_text(token, temporary)
        self._execute(
            guest,
            "python3",
            "-c",
            "import os,sys; os.chmod(sys.argv[1],0o600); os.replace(sys.argv[1],sys.argv[2])",
            temporary,
            self.capability_path,
        )

    def probe(self, *, count: int = 1, concurrency: int = 1) -> dict[int, int]:
        if not 1 <= count <= 1000 or not 1 <= concurrency <= 32:
            raise ValueError("Probe count must be 1 to 1000 and concurrency 1 to 32")
        output = self._execute(
            self.sandbox._sandbox,
            "python3",
            "-c",
            _PROBE,
            str(count),
            str(concurrency),
            self.relay_name,
            self.capability_path,
            timeout=120,
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

    @classmethod
    def close_named(cls, name: str) -> None:
        sandbox_class = cls._sandbox_class(cleanup=True)
        try:
            sandbox = modal.Sandbox.from_name(sandbox_class.DEFAULT_APP_NAME, name, include_terminated=True)
            if sandbox.poll() is None:
                sandbox.terminate()
        except NotFoundError:
            return

    @classmethod
    def close_sandbox(cls, sandbox_id: str) -> None:
        cls._sandbox_class(cleanup=True)
        try:
            sandbox = modal.Sandbox.from_id(sandbox_id)
            if sandbox.poll() is None:
                sandbox.terminate()
        except NotFoundError:
            return

    @classmethod
    def close_relay(cls, sandbox_id: str, relay_name: str) -> None:
        cls._sandbox_class(cleanup=True)
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", relay_name):
            raise ValueError("Invalid egress relay name")
        try:
            sandbox = modal.Sandbox.from_id(sandbox_id)
            if sandbox.poll() is not None:
                return
            try:
                sidecar = sandbox._experimental_sidecars.get(name=relay_name, include_terminated=True)
                if sidecar.poll() is None:
                    sidecar.terminate()
            except NotFoundError:
                pass
            capability_path = CAPABILITY_PATH if relay_name == RELAY_NAME else f"{CAPABILITY_PATH}.{relay_name}"
            try:
                sandbox.filesystem.remove(capability_path)
            except SandboxFilesystemNotFoundError:
                pass
        except NotFoundError:
            return
