"""pytest plugin: flag outbound network connections that escape to third-party hosts.

The default test suite must not make live outbound calls to third-party services.
Local infra (Postgres, Redis, ClickHouse, Kafka, Temporal, object storage, the egress
proxy) all resolve to loopback or private/link-local addresses. Any ``connect()`` to a
globally-routable IP is, by definition, a call leaving for the public internet — which
is what we want to surface.

Detection is by destination IP class, not a hostname allowlist: nothing to maintain as
service names change, and it can't be fooled by a hostname that happens to look local.

Record-only by default — the run finishes and we get a complete report. Pass
``--network-audit-block`` to turn each flagged connect into an immediate error (the
"firewall" mode), useful once the suite is supposed to be clean and you want CI to fail
on regressions.

Enable with: ``pytest -p network_audit ...`` (the dir is on pythonpath via pytest.ini's
``tools`` entries, or pass ``-p tools.network-audit...``; simplest is to add the dir to
``-p`` search by running from repo root with ``PYTHONPATH``). See the README.
"""

import os
import json
import socket
import fnmatch
import functools
import ipaddress
import traceback
from pathlib import Path
from typing import Any

import pytest

# Repo root = three levels up from this file (tools/network-audit/<file>).
_REPO_ROOT = Path(__file__).resolve().parents[2]


@functools.lru_cache(maxsize=4096)
def _is_global_ip(ip_str: str) -> bool:
    # Runs on every connect (loopback included), so cache the parse — destinations repeat
    # heavily within a session. is_global is false for loopback/private/link-local/CGNAT.
    try:
        return ipaddress.ip_address(ip_str).is_global
    except ValueError:
        return False


class _Recorder:
    def __init__(self) -> None:
        self.current_nodeid: str | None = None
        # ip -> last hostname seen resolving to it (best effort, for nicer reports)
        self.host_by_ip: dict[str, str] = {}
        # list of flagged events
        self.events: list[dict[str, Any]] = []
        self.block = False
        self.enforce = False
        # allowlist of known violations: list of {"host": str, "nodeid"?: str}.
        # nodeid omitted (or "*") allows any test to reach that host.
        self.baseline: list[dict[str, str]] = []

    def target_host(self, ev: dict[str, Any]) -> str:
        return ev["host"] or ev["ip"]

    def is_baselined(self, nodeid: str, host: str) -> bool:
        # host/nodeid are glob patterns (fnmatch). Host globs are what make the baseline
        # workable: live integration tests spin up sandboxes on ephemeral hostnames
        # (task-<random>.w.modal.host, test-file-downloads-<random>.s3.amazonaws.com) that
        # are never the same twice, so they can only be allowed by suffix — e.g. *.w.modal.host.
        for entry in self.baseline:
            if not fnmatch.fnmatch(host, entry.get("host", "*")):
                continue
            if fnmatch.fnmatch(nodeid, entry.get("nodeid", "*")):
                return True
        return False

    def new_violations(self) -> list[dict[str, Any]]:
        return [ev for ev in self.events if not self.is_baselined(ev["nodeid"], self.target_host(ev))]

    def note_resolution(self, host: str, results: list[Any]) -> None:
        for res in results:
            try:
                sockaddr = res[4]
                ip = sockaddr[0]
            except (IndexError, TypeError):
                continue
            self.host_by_ip[ip] = host

    def is_third_party(self, ip_str: str) -> bool:
        return _is_global_ip(ip_str)

    def app_frames(self) -> list[str]:
        # NETWORK_AUDIT_FULLSTACK keeps every frame (incl. site-packages) — needed to
        # identify egress on background threads (SDK consumer threads) that have no repo
        # frames at all, so the default repo-only filter would yield an empty stack.
        if os.getenv("NETWORK_AUDIT_FULLSTACK"):
            return [f"{fr.filename}:{fr.lineno} {fr.name}" for fr in traceback.extract_stack()][-15:]
        frames = []
        for frame in traceback.extract_stack():
            path = frame.filename
            if "/site-packages/" in path or "/network-audit/" in path:
                continue
            try:
                rel = str(Path(path).resolve().relative_to(_REPO_ROOT))
            except ValueError:
                continue
            frames.append(f"{rel}:{frame.lineno} {frame.name}")
        # The last few in-repo frames are the most informative (the call site).
        return frames[-6:]

    def record(self, ip: str, port: int) -> None:
        self.events.append(
            {
                "nodeid": self.current_nodeid or "<no active test>",
                "ip": ip,
                "port": port,
                "host": self.host_by_ip.get(ip),
                "stack": self.app_frames(),
            }
        )


_recorder = _Recorder()

_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_getaddrinfo = socket.getaddrinfo


def _patched_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
    results = _orig_getaddrinfo(host, *args, **kwargs)
    if isinstance(host, str):
        _recorder.note_resolution(host, results)
    return results


def _dest_ip_port(sock: socket.socket, address: Any) -> tuple[str, int] | None:
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return None  # AF_UNIX and friends carry a path, never a remote host
    try:
        ip, port = address[0], address[1]
    except (IndexError, TypeError):
        return None
    return ip, port


def _check(sock: socket.socket, address: Any) -> None:
    dest = _dest_ip_port(sock, address)
    if dest is None:
        return
    ip, port = dest
    if not _recorder.is_third_party(ip):
        return
    _recorder.record(ip, port)
    host = _recorder.host_by_ip.get(ip, ip)
    nodeid = _recorder.current_nodeid or "<no active test>"
    # Block mode only walls off *new* violations — anything in the baseline is a known,
    # tolerated offender being burned down separately. Background-thread egress (e.g. the
    # analytics consumer) can't be reliably walled here; the session-end gate catches those.
    if _recorder.block and not _recorder.is_baselined(nodeid, host):
        raise RuntimeError(
            f"network-audit: blocked outbound connection to third-party host {host} "
            f"({ip}:{port}) from test {nodeid}. "
            f"Move it to a tagged external-integration suite or mock the call."
        )


def _patched_connect(self, address):  # type: ignore[no-untyped-def]
    _check(self, address)
    return _orig_connect(self, address)


def _patched_connect_ex(self, address):  # type: ignore[no-untyped-def]
    _check(self, address)
    return _orig_connect_ex(self, address)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("network-audit")
    group.addoption(
        "--network-audit-block",
        action="store_true",
        default=False,
        help="Raise on outbound connections to third-party hosts instead of just recording them.",
    )
    group.addoption(
        "--network-audit-out",
        default=os.getenv("NETWORK_AUDIT_OUT", ".network-audit.json"),
        help="Path for the JSON report of flagged connections.",
    )
    group.addoption(
        "--network-audit-baseline",
        default=os.getenv("NETWORK_AUDIT_BASELINE"),
        help="Path to a baseline JSON of known/tolerated violations to ignore.",
    )
    group.addoption(
        "--network-audit-enforce",
        action="store_true",
        default=os.getenv("NETWORK_AUDIT_ENFORCE") == "1",
        help="Fail the test session at the end if any non-baselined violation was recorded "
        "(catches background-thread egress that --network-audit-block cannot).",
    )


def pytest_configure(config: pytest.Config) -> None:
    _recorder.block = config.getoption("--network-audit-block")
    _recorder.enforce = config.getoption("--network-audit-enforce")
    baseline_path = config.getoption("--network-audit-baseline")
    if baseline_path:
        data = json.loads(Path(baseline_path).read_text())
        _recorder.baseline = data.get("allow", []) if isinstance(data, dict) else data
    socket.socket.connect = _patched_connect  # type: ignore[method-assign,assignment]  # ty: ignore[invalid-assignment]
    socket.socket.connect_ex = _patched_connect_ex  # type: ignore[method-assign,assignment]  # ty: ignore[invalid-assignment]
    socket.getaddrinfo = _patched_getaddrinfo  # type: ignore[assignment]  # ty: ignore[invalid-assignment]


def pytest_unconfigure() -> None:
    socket.socket.connect = _orig_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _orig_connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = _orig_getaddrinfo  # type: ignore[assignment]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):  # type: ignore[no-untyped-def]
    _recorder.current_nodeid = item.nodeid
    yield
    _recorder.current_nodeid = None


def _resolve_out_path(config: pytest.Config) -> Path:
    # Turbo runs many pytest sessions per CI job; a single shared file would be clobbered
    # by the last session. With NETWORK_AUDIT_OUT_DIR set, each session writes its own
    # report-<pid>.json so the whole dir can be uploaded and merged.
    out_dir = os.getenv("NETWORK_AUDIT_OUT_DIR")
    if out_dir:
        path = Path(out_dir) / f"report-{os.getpid()}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return Path(config.getoption("--network-audit-out"))


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    out_path = _resolve_out_path(config)
    out_path.write_text(json.dumps({"events": _recorder.events}, indent=2))

    new = _recorder.new_violations()
    baselined = len(_recorder.events) - len(new)

    if not _recorder.events:
        terminalreporter.write_line("[network-audit] no third-party outbound connections detected", green=True)
        return

    # Group new violations by test, listing the distinct hosts each one reached.
    by_test: dict[str, set[str]] = {}
    for ev in new:
        by_test.setdefault(ev["nodeid"], set()).add(f"{_recorder.target_host(ev)}:{ev['port']}")

    if by_test:
        terminalreporter.section("network-audit: third-party outbound connections")
        for nodeid in sorted(by_test):
            terminalreporter.write_line(f"  {nodeid}", red=True)
            for target in sorted(by_test[nodeid]):
                terminalreporter.write_line(f"      -> {target}")
    suffix = f" ({baselined} baselined, ignored)" if baselined else ""
    terminalreporter.write_line(
        f"[network-audit] {len(by_test)} test(s) hit the public internet{suffix}; report: {out_path}"
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Setting session.exitstatus here propagates to pytest's return code: sessionfinish
    # runs in wrap_session's finally block, before `return session.exitstatus`.
    if _recorder.enforce and _recorder.new_violations() and exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
