import os
import sys
import json
import time
import fcntl
import shutil
import signal
import argparse
import tempfile
import subprocess
from pathlib import Path

WORKSPACE = Path("/tmp/workspace")
STATE = WORKSPACE / ".posthog/task-filesystem"
HOME_SEED = Path("/opt/posthog/task-home")
RUNTIME = Path("/run/posthog/task-filesystem")
VERSION = "1"
RUNTIME_TMP_PATHS = (
    "agent-env",
    "agent-github-env",
    "agent-oauth-env",
    "agentsh-bash-env.sh",
    "agentsh-env-wrapper.sh",
    "agentsh-session-id",
    "agent-server.pid",
    "agent-server.log",
    "agent-cli.pid",
    "posthog-memory-watchdog.json",
    "posthog-memory-watchdog.jsonl",
    "posthog-memory-watchdog.log",
    "posthog-preview",
    "start-dev-stack-preview.sh",
    "posthog-desktop-bootstrap",
)


def require_directory(path: Path) -> None:
    if path.resolve() != path:
        raise RuntimeError(f"Task filesystem path must be a real directory: {path}")
    path.mkdir(parents=True, exist_ok=True)


def bind(source: Path, destination: Path, *, recursive: bool = False) -> None:
    require_directory(destination)
    subprocess.run(["/usr/bin/mount", "--rbind" if recursive else "--bind", str(source), str(destination)], check=True)


def namespace_pid() -> int:
    state = json.loads((RUNTIME / "ready").read_text())
    pid = int(state["pid"])
    if pid <= 1 or Path(f"/proc/{pid}/ns/mnt").readlink().as_posix() != state["namespace"]:
        raise RuntimeError("Task filesystem namespace is no longer available")
    return pid


def hold() -> None:
    bind(WORKSPACE, RUNTIME / "workspace")
    bind(Path("/tmp"), RUNTIME / "tmp", recursive=True)
    backing = RUNTIME / "workspace/.posthog/task-filesystem"
    bind(backing / "tmp", Path("/tmp"))
    bind(RUNTIME / "workspace", WORKSPACE)
    bind(backing / "var-tmp", Path("/var/tmp"))
    bind(backing / "home", Path("/root"))
    for name in RUNTIME_TMP_PATHS:
        destination = Path("/tmp") / name
        target = RUNTIME / "tmp" / name
        if destination.is_symlink():
            if destination.readlink() != target:
                raise RuntimeError(f"Unexpected runtime path: {destination}")
        elif destination.exists():
            raise RuntimeError(f"Task file conflicts with runtime path: {destination}")
        else:
            destination.symlink_to(target)
    ready = RUNTIME / "ready"
    temporary = RUNTIME / "ready.tmp"
    temporary.write_text(json.dumps({"pid": os.getpid(), "namespace": str(Path("/proc/self/ns/mnt").readlink())}))
    temporary.replace(ready)
    while True:
        signal.pause()


def hold_after_user_mapping() -> None:
    if sys.stdin.read(1) != "1":
        raise RuntimeError("Task filesystem user mapping failed")
    arguments = ["/usr/bin/unshare", "--mount", "--propagation", "private", "/usr/bin/python3", "-I", __file__, "hold"]
    os.execv(arguments[0], arguments)


def prepare_runtime_home(home: Path) -> None:
    require_directory(home / ".claude")
    settings = home / ".claude/posthog-session-settings"
    target = RUNTIME / "claude-session-settings"
    require_directory(target)
    target.chmod(0o700)
    if settings.is_symlink():
        if settings.readlink() != target:
            raise RuntimeError(f"Unexpected runtime path: {settings}")
    else:
        if settings.exists():
            shutil.rmtree(settings)
        settings.symlink_to(target, target_is_directory=True)


def seed_home() -> None:
    require_directory(HOME_SEED)
    with tempfile.TemporaryDirectory(prefix=".home-", dir=HOME_SEED.parent) as temporary:
        copied = Path(temporary) / "home"
        subprocess.run(["/usr/bin/cp", "--archive", "--", "/root", str(copied)], check=True)
        shutil.rmtree(HOME_SEED)
        copied.rename(HOME_SEED)


def prepare_home() -> None:
    home = STATE / "home"
    if home.resolve() != home:
        raise RuntimeError(f"Task filesystem path must be a real directory: {home}")
    if not home.is_dir():
        if (STATE / "version").exists() or not HOME_SEED.is_dir() or HOME_SEED.resolve() != HOME_SEED:
            raise RuntimeError("Task filesystem home must be seeded during image build")
        HOME_SEED.rename(home)
    prepare_runtime_home(home)


def initialize(runtime: str) -> None:
    require_directory(RUNTIME)
    with (RUNTIME / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (RUNTIME / "ready").exists():
            try:
                namespace_pid()
            except (FileNotFoundError, ProcessLookupError, RuntimeError):
                (RUNTIME / "ready").unlink()
            else:
                return
        require_directory(STATE)
        version = STATE / "version"
        if version.is_symlink() or (version.exists() and version.read_text().strip() != VERSION):
            raise RuntimeError("Unsupported task filesystem version")
        for name in ("tmp", "var-tmp"):
            require_directory(STATE / name)
            (STATE / name).chmod(0o1777)
        prepare_home()
        for process_path in Path("/proc").iterdir():
            if not process_path.name.isdigit():
                continue
            try:
                if (process_path / "comm").read_text().strip() == "dockerd":
                    raise RuntimeError("Docker must start after the task filesystem is initialized")
            except (FileNotFoundError, ProcessLookupError):
                continue
        arguments = ["/usr/bin/unshare"]
        if runtime == "gvisor":
            arguments.extend(["--user", "--keep-caps", "/usr/bin/python3", "-I", __file__, "map-user"])
        else:
            arguments.extend(["--mount", "--propagation", "private", "/usr/bin/python3", "-I", __file__, "hold"])
        with (RUNTIME / "setup.log").open("w") as log:
            process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=log, stderr=log, start_new_session=True)
        try:
            deadline = time.monotonic() + 15
            if runtime == "gvisor":
                while Path(f"/proc/{process.pid}/ns/user").readlink() == Path("/proc/self/ns/user").readlink():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("Task filesystem user namespace did not start")
                    time.sleep(0.01)
                for name in ("uid_map", "gid_map"):
                    mapping = ""
                    for line in Path(f"/proc/self/{name}").read_text().splitlines():
                        start, _, count = line.split()
                        mapping += f"{start} {start} {count}\n"
                    Path(f"/proc/{process.pid}/{name}").write_text(mapping)
                assert process.stdin is not None
                process.stdin.write(b"1")
                process.stdin.flush()
            assert process.stdin is not None
            process.stdin.close()
            while not (RUNTIME / "ready").exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f"Task filesystem setup failed: {(RUNTIME / 'setup.log').read_text()[-2000:]}")
                time.sleep(0.05)
            namespace_pid()
            version.write_text(VERSION)
            (RUNTIME / "runtime").write_text(runtime)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            (RUNTIME / "ready").unlink(missing_ok=True)
            raise


def enter(command: list[str]) -> None:
    if not (RUNTIME / "ready").exists() and not (STATE / "version").exists():
        os.execvp(command[0], command)
    pid = namespace_pid()
    if Path("/proc/self/ns/mnt").readlink() == Path(f"/proc/{pid}/ns/mnt").readlink():
        os.execvp(command[0], command)
    arguments = ["/usr/bin/nsenter", "--target", str(pid)]
    if (RUNTIME / "runtime").read_text() == "gvisor":
        arguments.append("--user")
    arguments.extend(["--mount", f"--wdns={os.getcwd()}", "--", *command])
    os.execv(arguments[0], arguments)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("seed-home", "initialize", "hold", "map-user", "enter"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.operation == "seed-home":
        if args.arguments:
            parser.error("seed-home takes no arguments")
        seed_home()
    elif args.operation == "initialize":
        if args.arguments not in (["vm"], ["gvisor"]):
            parser.error("initialize requires vm or gvisor")
        initialize(args.arguments[0])
    elif args.operation == "hold":
        hold()
    elif args.operation == "map-user":
        hold_after_user_mapping()
    else:
        command = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        if not command:
            parser.error("enter requires a command")
        enter(command)


if __name__ == "__main__":
    main()
