# ruff: noqa: T201
from __future__ import annotations

import os
import re
import sys
import json
import time
import errno
import fcntl
import socket
import hashlib
import tarfile
import argparse
import tempfile
import subprocess
import http.client
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import django
from django.db import DatabaseError

from pydantic import ValidationError

from products.posthog_ai.eval_harness.environment.dataset import EnvironmentDataset
from products.posthog_ai.eval_harness.environment.download import S3EnvironmentSource, validate_sha256
from products.posthog_ai.eval_harness.environment.guard import EnvironmentMigrationsPending, assert_local_databases
from products.posthog_ai.eval_harness.environment.schema import EnvironmentTextPolicy

if TYPE_CHECKING:
    from products.posthog_ai.eval_harness.environment.restore import PreparedEnvironment

REPO_ROOT = Path(__file__).resolve().parents[4]
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_ARCHIVE_MEMBERS = 10_000
APP_PORTS = (8000, 8010, 8234)


def require_private_path(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError(f"Private input and state paths must not be symlinks: {path}")
    resolved = path.resolve()
    directory = resolved if resolved.is_dir() else resolved.parent
    while not directory.exists():
        directory = directory.parent
    repository = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=directory, check=False, capture_output=True, text=True
    )
    if repository.returncode == 0:
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", str(resolved)],
            cwd=repository.stdout.strip(),
            check=False,
        )
        if ignored.returncode != 0:
            raise ValueError(f"Private fixture data and state must be outside Git or ignored: {resolved}")
    elif "not a git repository" not in repository.stderr:
        raise ValueError("Could not check whether private storage is ignored by Git")
    return resolved


def file_sha256(path: Path) -> str:
    with path.open("rb") as content:
        return hashlib.file_digest(content, "sha256").hexdigest()


def relative_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or any(part in {".", "..", ""} for part in name.split("/")):
        raise ValueError("Bundle paths must be normalized relative paths")
    return path


def regular_files(folder: Path) -> set[Path]:
    files: set[Path] = set()
    for path in folder.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("Fixture folders may contain only regular files and directories")
        if path.is_file():
            files.add(path)
    return files


def verify_checksums(folder: Path, *, required: bool = False) -> None:
    files = regular_files(folder)
    manifest = folder / "SHA256SUMS"
    if not manifest.is_file():
        if required:
            raise ValueError("An archived fixture bundle requires SHA256SUMS")
        return
    expected: set[Path] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            raise ValueError("Invalid SHA256SUMS entry")
        path = folder / relative_member(match[2])
        if path in expected or path == manifest:
            raise ValueError("Duplicate or self-referencing SHA256SUMS entry")
        if not path.is_file() or file_sha256(path) != match[1]:
            raise ValueError(f"Fixture checksum mismatch: {path.relative_to(folder)}")
        expected.add(path)
    if files - {manifest} != expected:
        raise ValueError("SHA256SUMS must cover every bundled file exactly once")


class EnvironmentInput:
    @staticmethod
    def _bundle_root(folder: Path) -> Path:
        if (folder / "SHA256SUMS").is_file() and (folder / "environment.json").is_file():
            return folder
        children = list(folder.iterdir())
        if (
            len(children) == 1
            and children[0].is_dir()
            and (children[0] / "SHA256SUMS").is_file()
            and (children[0] / "environment.json").is_file()
        ):
            return children[0]
        raise ValueError("The archive must contain one environment folder with environment.json and SHA256SUMS")

    @classmethod
    def unpack(cls, source: Path, workspace: Path) -> Path:
        if source.is_dir():
            verify_checksums(source)
            return source
        if not source.is_file() or not source.name.endswith(".tar.gz"):
            raise ValueError("Provide an unpacked fixture folder or a .tar.gz fixture bundle")
        destination = workspace / f"bundle-{file_sha256(source)}"
        if destination.exists():
            if destination.is_symlink() or not destination.is_dir():
                raise ValueError("The extracted bundle path must be a private directory")
            regular_files(destination)
            root = cls._bundle_root(destination)
            verify_checksums(root, required=True)
            return root
        with tempfile.TemporaryDirectory(prefix=".unpack-", dir=workspace) as temporary:
            staging = Path(temporary)
            with tarfile.open(source, "r:gz") as archive:
                members: list[tarfile.TarInfo] = []
                seen: set[PurePosixPath] = set()
                total = 0
                for member in archive:
                    path = relative_member(member.name.rstrip("/") if member.isdir() else member.name)
                    if path in seen or not (member.isfile() or member.isdir()) or member.size < 0:
                        raise ValueError("Archive entries must be unique regular files or directories, without links")
                    seen.add(path)
                    total += member.size
                    if len(seen) > MAX_ARCHIVE_MEMBERS or total > MAX_ARCHIVE_BYTES:
                        raise ValueError("Fixture archive exceeds the file-count or uncompressed-size limit")
                    members.append(member)
                for member in members:
                    target = staging / member.name
                    if member.isdir():
                        target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                        content = archive.extractfile(member)
                        if content is None:
                            raise ValueError("Archive regular file has no content")
                        with content, target.open("xb") as output:
                            while block := content.read(1024 * 1024):
                                output.write(block)
                        target.chmod(0o600)
            root = cls._bundle_root(staging)
            verify_checksums(root, required=True)
            for directory in staging.rglob("*"):
                if directory.is_dir():
                    directory.chmod(0o700)
            relative_root = root.relative_to(staging)
            staging.rename(destination)
        return destination / relative_root


@contextmanager
def workspace_lock(workspace: Path) -> Iterator[None]:
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    workspace.chmod(0o700)
    descriptor = os.open(workspace / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another fixture preparation is using this state directory") from error
        yield


class LocalApp:
    @staticmethod
    def status(path: str) -> int | None:
        connection = http.client.HTTPConnection("127.0.0.1", 8010, timeout=3)
        try:
            connection.request("GET", path, headers={"Host": "localhost:8010"})
            return connection.getresponse().status
        except (OSError, http.client.HTTPException):
            return None
        finally:
            connection.close()

    @classmethod
    def healthy(cls) -> bool:
        return (
            cls.status("/_health") == 200
            and cls.status("/") in {200, 302}
            and cls.status("/api/projects/@current") == 401
        )

    @staticmethod
    def occupied_ports() -> list[int]:
        occupied: list[int] = []
        for port in APP_PORTS:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                try:
                    probe.bind(("0.0.0.0", port))
                except OSError as error:
                    if error.errno != errno.EADDRINUSE:
                        raise
                    occupied.append(port)
        return occupied

    @staticmethod
    def process_status(checkout: str, process: str) -> dict[str, object] | None:
        digest = hashlib.sha256(checkout.encode()).hexdigest()[:8]
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            try:
                client.connect(f"/tmp/phrocs-{digest}.sock")
                client.sendall(json.dumps({"cmd": "status", "process": process}).encode() + b"\n")
                response = bytearray()
                while len(response) < 65_536 and not response.endswith(b"\n"):
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    response.extend(chunk)
                status: dict[str, object] = json.loads(response)
                if isinstance(status, dict) and status.get("ok"):
                    return status
            except (OSError, ValueError, TypeError):
                pass
        return None

    @classmethod
    def checkout(cls) -> str | None:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        candidates: list[str] = []
        for line in result.stdout.splitlines():
            if not line.startswith("worktree "):
                continue
            root = str(Path(line.removeprefix("worktree ")).resolve())
            status = cls.process_status(root, "backend")
            if status is not None and status.get("ready"):
                candidates.append(root)
        return candidates[0] if len(candidates) == 1 else None

    @classmethod
    def wait_for_migrations(cls, checkout: str | None, *, timeout: int) -> None:
        if checkout is None:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            complete = True
            for process in ("migrate-postgres", "migrate-clickhouse"):
                status = cls.process_status(checkout, process)
                if status is not None and status.get("status") == "done" and status.get("exit_code") == 0:
                    continue
                complete = False
                if status is None or status.get("status") not in {"pending", "starting", "running"}:
                    raise ValueError(f"App migrations are not ready in {checkout}; inspect {process} before importing.")
            if complete:
                return
            time.sleep(2)
        raise ValueError(f"App migrations did not finish within {timeout}s in {checkout}")

    @staticmethod
    def ensure_postgres_migrations(
        backend: type[PreparedEnvironment], *, checkout: str | None, workspace: Path, timeout: int
    ) -> None:
        try:
            backend.assert_migrations_current()
            return
        except EnvironmentMigrationsPending:
            if checkout is None or Path(checkout).resolve() != REPO_ROOT.resolve():
                raise ValueError(
                    "This checkout needs database migrations, but the running app belongs to another or unknown "
                    "checkout. Start the normal app from this checkout before preparing fixtures. "
                    "No migrations or project import were started."
                ) from None
        log_path = workspace / "migrations.log"
        if log_path.is_symlink():
            raise ValueError("The migration log must not be a symlink")
        print(f"Applying this checkout's pending database migrations; log: {log_path}", flush=True)
        descriptor = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as log:
            os.fchmod(log.fileno(), 0o600)
            for arguments in (("migrate", "--noinput"), ("migrate_product_databases",)):
                try:
                    subprocess.run(
                        [str(REPO_ROOT / ".codex/with-flox"), "python", "manage.py", *arguments],
                        cwd=REPO_ROOT,
                        stdout=log,
                        stderr=log,
                        check=True,
                        timeout=timeout,
                    )
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                    raise ValueError(
                        f"Database migration failed; inspect {log_path}. No project import was started."
                    ) from error
        backend.assert_migrations_current()

    @classmethod
    def ensure(cls, *, timeout: int, workspace: Path) -> str | None:
        if cls.healthy():
            checkout = cls.checkout()
            cls.wait_for_migrations(checkout, timeout=timeout)
            return checkout
        occupied = cls.occupied_ports()
        if occupied:
            raise ValueError(
                f"The app is not healthy and ports {occupied} are occupied. "
                "Inspect the existing dev stack; this command will not stop or replace it."
            )
        log_path = workspace / "app-start.log"
        if log_path.is_symlink():
            raise ValueError("The startup log must not be a symlink")
        print(f"Starting the dev app; startup log: {log_path}", flush=True)
        command = [
            str(REPO_ROOT / ".codex/with-flox"),
            "env",
            "HOGLI_SKIP_ZOMBIE_CHECK=1",
            "HOGLI_SKIP_GIT_CHECK=1",
            "hogli",
            "up",
            "-d",
            "-y",
        ]
        descriptor = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as log:
            os.fchmod(log.fileno(), 0o600)
            try:
                subprocess.run(command, cwd=REPO_ROOT, stdout=log, stderr=log, check=True, timeout=timeout)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                raise ValueError(
                    f"Dev app startup failed; inspect {log_path}. Existing services were left running."
                ) from error
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cls.healthy():
                checkout = cls.checkout() or str(REPO_ROOT)
                cls.wait_for_migrations(checkout, timeout=timeout)
                return checkout
            time.sleep(2)
        raise ValueError(f"The app did not become ready within {timeout}s; inspect {log_path} and hogli process logs.")


def load_backend() -> type[PreparedEnvironment]:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    django.setup()
    from products.posthog_ai.eval_harness.environment.restore import (
        PreparedEnvironment,  # noqa: PLC0415 -- models need configured Django.
    )

    return PreparedEnvironment


def parse_cutoff(value: str) -> datetime:
    try:
        cutoff = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("The cutoff must be an ISO datetime with a timezone") from error
    if cutoff.tzinfo is None:
        raise argparse.ArgumentTypeError("The cutoff must include a timezone")
    return cutoff.astimezone(UTC)


def positive_integer(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("The value must be positive")
    return result


def project_link(team_id: int) -> str:
    site = os.environ.get("SITE_URL", "http://localhost:8010").rstrip("/")
    parsed = urlsplit(site)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        site = "http://localhost:8010"
    return f"{site}/project/{team_id}/activity/explore"


def validate_receipt(
    dataset: EnvironmentDataset, workspace: Path, target_cutoff: datetime | None, user_id: int | None
) -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    databases = assert_local_databases()
    receipt_path = workspace / "receipt.json"
    if receipt_path.is_symlink():
        raise ValueError("The import receipt must not be a symlink")
    if receipt_path.exists():
        captured: object = json.loads(receipt_path.read_bytes())
        if not isinstance(captured, dict) or captured.get("phase") != "complete":
            raise ValueError("The previous import is incomplete; use a fresh --state-dir")
        if (
            captured.get("manifest_sha256") != dataset.manifest_sha256
            or captured.get("databases") != databases
            or (target_cutoff is not None and parse_cutoff(str(captured.get("target_cutoff"))) != target_cutoff)
            or (user_id is not None and captured.get("user_id") != user_id)
        ):
            raise ValueError("The existing receipt belongs to different import inputs; use a fresh --state-dir")


def source_provenance(app_checkout: str | None) -> dict[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    diff = subprocess.run(["git", "diff", "--binary", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    hashes = {
        name: file_sha256(REPO_ROOT / name)
        for raw_name in untracked.split(b"\0")
        if raw_name and (name := os.fsdecode(raw_name)) and (REPO_ROOT / name).is_file()
    }
    provenance = {
        "importer_commit": commit,
        "importer_checkout": str(REPO_ROOT),
        "importer_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "importer_untracked_sha256": json.dumps(hashes, sort_keys=True),
    }
    if app_checkout is not None:
        provenance["app_checkout"] = app_checkout
    return provenance


def prepare(args: argparse.Namespace) -> None:
    source: Path | S3EnvironmentSource
    if "://" in str(args.environment):
        source = S3EnvironmentSource(str(args.environment), sha256=args.sha256, profile=args.aws_profile)
    else:
        if args.aws_profile is not None:
            raise ValueError("--aws-profile applies only to S3 inputs")
        source = require_private_path(Path(args.environment))
        if not source.exists():
            raise ValueError("The fixture input does not exist")
        if args.sha256 is not None:
            expected = validate_sha256(args.sha256)
            if not source.is_file() or file_sha256(source) != expected:
                raise ValueError("The local bundle does not match --sha256")
    workspace = require_private_path(args.state_dir)
    if isinstance(source, Path) and (workspace == source or workspace.is_relative_to(source)):
        raise ValueError("The state directory must be outside the fixture folder")
    with workspace_lock(workspace):
        print("Validating the environment data...", flush=True)
        source_path = source.fetch(workspace) if isinstance(source, S3EnvironmentSource) else source
        folder = EnvironmentInput.unpack(source_path, workspace)
        dataset = EnvironmentDataset.load(folder / "environment.json")
        validate_receipt(dataset, workspace, args.target_cutoff, args.user_id)
        app_checkout = LocalApp.ensure(timeout=args.timeout, workspace=workspace)
        backend = load_backend()
        LocalApp.ensure_postgres_migrations(backend, checkout=app_checkout, workspace=workspace, timeout=args.timeout)
        print("Preparing the project and checking its data...", flush=True)
        provenance = source_provenance(app_checkout)
        if isinstance(source, S3EnvironmentSource):
            provenance.update(bundle_source=source.uri, bundle_sha256=source.sha256)
        result = backend.restore(
            dataset,
            workspace=workspace,
            target_cutoff=args.target_cutoff,
            user_id=args.user_id,
            provenance=provenance,
        )
        print(f"{'Reused' if result.reused else 'Prepared'} project with {result.event_count:,} events.")
        print(f"Project: {project_link(result.team_id)}")
        print(f"Target cutoff: {result.target_cutoff.isoformat()}")
        print(f"Receipt: {result.receipt_path}")
        if result.credentials_path is not None:
            print(f"Login credentials: {result.credentials_path}")
        print("The dev app remains running. No agent or evaluation was started.")


def pack(args: argparse.Namespace) -> None:
    event_paths = [require_private_path(path) for path in args.events]
    metrics_path = require_private_path(args.metrics) if args.metrics is not None else None
    output = require_private_path(args.output)
    if output.exists() or not output.name.endswith(".tar.gz"):
        raise ValueError("Use a new .tar.gz output path; existing files are never replaced")
    policy = EnvironmentTextPolicy()
    if args.text_policy is not None:
        policy_path = require_private_path(args.text_policy)
        policy = EnvironmentTextPolicy.model_validate_json(policy_path.read_bytes())
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    print("Validating and packing the environment data...", flush=True)
    with tempfile.TemporaryDirectory(prefix=".environment-pack-", dir=output.parent) as temporary:
        staging = Path(temporary)
        folder = staging / "environment"
        dataset = EnvironmentDataset.build(
            folder,
            environment_id=args.name,
            event_paths=event_paths,
            metrics_path=metrics_path,
            source_cutoff=args.source_cutoff,
            timezone=args.timezone,
            time_strings=policy.time_strings,
            string_replacements=policy.string_replacements,
        )
        expected_files = {dataset.path}
        expected_files.update(reference.resolve(folder) for reference in dataset.manifest.events)
        if dataset.manifest.metrics is not None:
            expected_files.add(dataset.manifest.metrics.resolve(folder))
        if regular_files(folder) != expected_files:
            raise ValueError("The builder produced files outside the environment manifest")
        sums = "".join(
            f"{file_sha256(path)}  {path.relative_to(folder).as_posix()}\n" for path in sorted(expected_files)
        )
        (folder / "SHA256SUMS").write_text(sums, encoding="utf-8")
        (folder / "SHA256SUMS").chmod(0o600)
        verify_checksums(folder, required=True)
        archive_path = staging / "bundle.tar.gz"
        descriptor = os.open(archive_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as file, tarfile.open(fileobj=file, mode="w:gz") as archive:
            members = [folder, *sorted(folder.rglob("*"))]
            if (
                len(members) > MAX_ARCHIVE_MEMBERS
                or sum(path.stat().st_size for path in members if path.is_file()) > MAX_ARCHIVE_BYTES
            ):
                raise ValueError("Environment bundle exceeds the file-count or uncompressed-size limit")
            for path in members:
                item = archive.gettarinfo(str(path), arcname=str(path.relative_to(staging)))
                item.uid = item.gid = 0
                item.uname = item.gname = ""
                item.mtime = 0
                item.mode = 0o700 if path.is_dir() else 0o600
                if path.is_dir():
                    archive.addfile(item)
                else:
                    with path.open("rb") as content:
                        archive.addfile(item, content)
        os.link(archive_path, output)
    print(f"Environment bundle: {output}")
    print(f"SHA256: {file_sha256(output)}")
    print(f"Contains {dataset.manifest.event_count:,} events and {dataset.manifest.metric_count:,} metrics.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a persistent local PostHog project from private saved fixtures."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="Restore a persistent local project")
    prepare_parser.add_argument(
        "environment", help="Environment folder, private .tar.gz bundle, or s3://bucket/key.tar.gz"
    )
    prepare_parser.add_argument("--sha256", help="Published archive SHA-256; required for S3 inputs")
    prepare_parser.add_argument("--aws-profile", help="AWS profile from ~/.aws/config; applies only to S3 inputs")
    prepare_parser.add_argument("--state-dir", type=Path, default=REPO_ROOT / ".flox/cache/eval-environment")
    prepare_parser.add_argument(
        "--target-cutoff", type=parse_cutoff, help="First import defaults to UTC now; reruns reuse the receipt"
    )
    prepare_parser.add_argument(
        "--user-id", type=positive_integer, help="Existing active user to own the new local project"
    )
    prepare_parser.add_argument(
        "--timeout", type=positive_integer, default=600, help="App startup/readiness timeout in seconds"
    )
    pack_parser = commands.add_parser("pack", help="Build a portable environment from typed Parquet files")
    pack_parser.add_argument("--events", type=Path, nargs="+", required=True)
    pack_parser.add_argument("--metrics", type=Path)
    pack_parser.add_argument("--source-cutoff", type=parse_cutoff, required=True)
    pack_parser.add_argument("--name", "--source-id", dest="name", required=True, help="Stable environment identifier")
    pack_parser.add_argument("--timezone", default="UTC")
    pack_parser.add_argument("--text-policy", type=Path, help="Reviewed JSON time_strings/string_replacements policy")
    pack_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    invocation_dir = Path(os.environ.get("EVAL_ENVIRONMENT_INVOCATION_DIR", Path.cwd()))
    if args.command == "prepare":
        if "://" not in args.environment:
            args.environment = invocation_dir / args.environment
        args.state_dir = invocation_dir / args.state_dir
    else:
        args.events = [invocation_dir / path for path in args.events]
        args.metrics = invocation_dir / args.metrics if args.metrics else None
        args.text_policy = invocation_dir / args.text_policy if args.text_policy else None
        args.output = invocation_dir / args.output
    os.umask(0o077)
    try:
        if args.command == "prepare":
            prepare(args)
        else:
            pack(args)
    except ValidationError:
        print(
            "Could not prepare the environment: input validation failed. Private field values were not printed.",
            file=sys.stderr,
        )
        return 1
    except DatabaseError as error:
        print(
            f"Could not prepare the devbox: local database operation failed ({type(error).__name__}). "
            "Check database readiness and the import receipt before retrying.",
            file=sys.stderr,
        )
        return 1
    except (
        ValueError,
        RuntimeError,
        OSError,
        tarfile.TarError,
        subprocess.SubprocessError,
        argparse.ArgumentTypeError,
    ) as error:
        print(f"Could not prepare the devbox: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
