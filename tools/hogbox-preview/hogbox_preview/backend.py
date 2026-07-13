"""The preview *layer* seam.

A ``PreviewBackend`` is "a box we can run a docker stack inside and reach over
HTTP". Swapping the layer — hogland today, DigitalOcean before that, something
else next — means writing one new backend. Everything about *what* runs in the
box (the PostHog stack: compose, image, migrate, seed) lives in ``stack.py`` and
never changes when the layer changes.

The split, concretely:
  - LAYER  (this file + *_backend.py): what box to provision, how to ssh / which
    SDK to call, what its public URL is, how to tear it down.
  - STACK  (stack.py): the docker-compose recipe, run through the backend's
    ``exec`` / ``write_file`` / ``run_long`` — blind to which provider it's on.

Most backends reach the box over ssh, so ``SSHBackend`` implements
``exec``/``write_file`` once; a provider subclass only supplies ``provision``,
``ssh_target``, ``web_url`` and ``destroy``. A future SDK-only backend can skip
``SSHBackend`` and implement the abstract methods directly.
"""

from __future__ import annotations

import abc
import time
import shlex
import subprocess
import dataclasses


@dataclasses.dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclasses.dataclass
class SSHTarget:
    """How to reach a box over ssh. This — host/port/user/key — is the whole of
    what differs between layers at the data-plane level."""

    host: str
    port: int = 22
    user: str = "root"
    key_path: str | None = None  # None -> ssh's default identity


class PreviewBackend(abc.ABC):
    """A box that can host the PostHog docker stack and serve it over HTTP.

    ``web_port`` is the in-guest port the stack listens on; the backend exposes
    it at ``web_url`` (for hogland, the box-front edge; for a droplet, its
    domain). The stack is told this port and nothing else about the provider.
    """

    def __init__(self, *, web_port: int = 8000):
        self.web_port = web_port

    # --- layer-specific: each provider implements these four -----------------
    @abc.abstractmethod
    def provision(self) -> None:
        """Create/restore the box and expose ``web_port``. Idempotent."""

    def attach(self) -> None:
        """Bind to the EXISTING box for this preview WITHOUT restoring a new one —
        the non-creating counterpart to ``provision``. Used by the deferred
        frontend swap, which must act on the box ``bring_up`` already stood up.
        Default: fall back to ``provision`` for layers where that's idempotent
        reuse; the hogland layer overrides it (there ``provision`` restores a
        fresh box, which a swap must never do)."""
        self.provision()

    @abc.abstractmethod
    def exec(self, command: str, *, timeout: int = 120) -> ExecResult:
        """Run a shell command in the box and capture its output."""

    @abc.abstractmethod
    def write_file(self, remote_path: str, content: bytes | str) -> None:
        """Write ``content`` (text or raw bytes) to ``remote_path`` in the box."""

    @property
    @abc.abstractmethod
    def web_url(self) -> str:
        """Externally reachable, root-served base URL for ``web_port``."""

    @abc.abstractmethod
    def destroy(self) -> None:
        """Tear the box down."""

    # --- provider-agnostic conveniences, built on exec/write_file ------------
    def run_long(self, script: str, *, name: str, timeout: int = 1800, interval: int = 3) -> ExecResult:
        """Run a slow command (image pull, migrate, seed) detached so it
        outlives the control channel, then poll a marker until it finishes.

        The detach matters: a multi-minute command run synchronously trips
        exec deadlines / connection drops. ``setsid`` + a ``.done``/``.fail``
        marker file is the portable way to launch-and-wait through any
        ``exec`` implementation. Returns the tail of the captured log.

        ``interval`` is the marker poll period: each completed step pays up to
        one interval of dead air before we notice it's done, so it's kept tight
        (3s) — the bring-up has a handful of run_long steps and a 10s poll added
        a visible chunk of pure waiting across them. Each probe is one cheap
        exec round-trip, so 3s is comfortably affordable.
        """
        base = f"/tmp/hogbox-{name}"
        log, done, fail = f"{base}.log", f"{base}.done", f"{base}.fail"
        self.write_file(f"{base}.sh", script + "\n")
        inner = f"bash {base}.sh > {log} 2>&1 && touch {done} || touch {fail}"
        launch = f"rm -f {done} {fail}; setsid bash -c {shlex.quote(inner)} </dev/null >/dev/null 2>&1 & echo launched"
        self.exec(launch, timeout=60)

        deadline = time.time() + timeout
        while time.time() < deadline:
            probe = self.exec(
                f"if [ -f {done} ]; then echo DONE; elif [ -f {fail} ]; then echo FAIL; else echo RUN; fi",
                timeout=30,
            )
            state = probe.stdout.strip().splitlines()[-1] if probe.stdout.strip() else "RUN"
            if state == "DONE":
                return self.exec(f"tail -n 80 {log}", timeout=30)
            if state == "FAIL":
                tail = self.exec(f"tail -n 60 {log}", timeout=30).stdout
                raise RuntimeError(f"{name} failed:\n{tail}")
            time.sleep(interval)
        tail = self.exec(f"tail -n 60 {log}", timeout=30).stdout
        raise TimeoutError(f"{name} did not finish within {timeout}s:\n{tail}")

    def wait_http_ok(self, url_path: str, *, expect: int = 200, timeout: int = 600, interval: int = 3) -> None:
        """Poll an in-box HTTP path until it returns ``expect`` (probed from
        inside the box, so it's independent of external networking). 3s poll so
        we don't sit on up to 10s of dead air after web actually starts serving."""
        target = f"http://localhost:{self.web_port}{url_path}"
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            r = self.exec(f"curl -s -o /dev/null -w '%{{http_code}}' -m 15 {target}", timeout=30)
            last = r.stdout.strip()
            if last == str(expect):
                return
            time.sleep(interval)
        raise TimeoutError(f"{target} never returned {expect} (last={last})")


class SSHBackend(PreviewBackend):
    """A ``PreviewBackend`` reached over ssh. Subclasses supply ``ssh_target``
    plus the four layer methods; ``exec``/``write_file`` are shared here so
    every ssh-based provider gets them for free."""

    # ssh options: non-interactive, don't pollute known_hosts, fail fast.
    # nosemgrep: trailofbits.generic.ssh-disable-host-key-checking.ssh-disable-host-key-checking
    _SSH_OPTS = [
        "-o",
        "StrictHostKeyChecking=no",  # ephemeral throwaway boxes with rotating IPs, no stable host key to pin
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "ServerAliveInterval=15",
    ]

    @abc.abstractmethod
    def ssh_target(self) -> SSHTarget: ...

    def _ssh_argv(self, target: SSHTarget) -> list[str]:
        argv = ["ssh", *self._SSH_OPTS, "-p", str(target.port)]
        if target.key_path:
            argv += ["-i", target.key_path, "-o", "IdentitiesOnly=yes"]
        argv.append(f"{target.user}@{target.host}")
        return argv

    def exec(self, command: str, *, timeout: int = 120) -> ExecResult:
        argv = [*self._ssh_argv(self.ssh_target()), command]
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout + 30)
            return ExecResult(p.returncode, p.stdout, p.stderr)
        except subprocess.TimeoutExpired as e:
            return ExecResult(124, e.stdout or "", f"ssh exec timed out after {timeout}s")

    def write_file(self, remote_path: str, content: bytes | str) -> None:
        # Pipe the body over stdin into `cat >` so no quoting/heredoc games. The
        # contract is bytes|str (stack.swap_frontend ships a binary tar), so run
        # in binary mode and encode text — text=True would corrupt raw bytes.
        data = content.encode() if isinstance(content, str) else content
        argv = [*self._ssh_argv(self.ssh_target()), f"cat > {shlex.quote(remote_path)}"]
        p = subprocess.run(argv, input=data, capture_output=True, timeout=60)
        if p.returncode != 0:
            raise RuntimeError(f"write_file({remote_path}) failed: {p.stderr.decode(errors='replace').strip()}")
