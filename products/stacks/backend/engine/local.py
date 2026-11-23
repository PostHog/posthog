from __future__ import annotations

import os
import sys
import json
import fcntl
import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Never, cast

from .runner import run_diff, run_push
from .translate_in import translate_in
from .types import Binding, BindingRecord, Credentials, EngineError, EngineOptions, StackDescription


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.exit(2, "Check the arguments. Use --help to see the available options.\n")


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _Parser(prog="stack", description="Compare and push a stack from a local description.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("diff", "push"):
        command = commands.add_parser(name)
        command.add_argument("description", type=Path)
        command.add_argument("--host", required=True)
        command.add_argument("--project-id", required=True, type=int)
        command.add_argument("--snapshot", type=Path, help="Private file that remembers this stack's bindings.")
        command.add_argument("--state", dest="snapshot", type=Path, help=argparse.SUPPRESS)
        command.add_argument("--rename-map", type=Path)
        command.add_argument(
            "--saved-diff", type=Path, required=name == "push", help="Private file for the diff to push."
        )
        command.add_argument(
            "--mirror",
            default=os.getenv("POSTHOG_STACK_MIRROR"),
            help="Directory containing the installed stack dependencies. Defaults to POSTHOG_STACK_MIRROR.",
        )
        command.add_argument("--allow-registry", action="store_true", help="Allow downloads on a development machine.")
        command.add_argument("--timeout-seconds", type=float, help="Maximum duration of this run in seconds.")
        if name == "diff":
            command.add_argument(
                "--secrets-file", type=Path, help="Private JSON object of named secrets for this environment."
            )
    return parser.parse_args(argv)


def _write(path: Path, data: bytes) -> None:
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


@contextmanager
def _snapshot_lock(path: Path) -> Iterator[None]:
    with (path.parent / (path.name + ".lock")).open("ab") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise EngineError(
                [
                    {
                        "code": "stack_locked",
                        "message": "Another push is running. Wait for it to finish, then run diff again.",
                    }
                ]
            ) from None
        yield


def _read_snapshot(path: Path | None) -> tuple[bytes | None, list[Binding]]:
    if not path or not path.exists():
        return None, []
    raw = path.read_bytes()
    if not raw:
        return None, []
    snapshot = json.loads(raw)
    if not isinstance(snapshot, dict) or "posthog_adopted_bindings" not in snapshot:
        return raw, []
    adopted = snapshot.pop("posthog_adopted_bindings")
    return json.dumps(snapshot).encode(), adopted


def _write_snapshot(path: Path, snapshot: bytes, bindings: list[BindingRecord]) -> None:
    adopted = [binding for binding in bindings if binding.get("origin") == "adopted"]
    if adopted:
        # The local caller stores ownership with the snapshot so an interrupted write cannot separate the two.
        record = json.loads(snapshot)
        record["posthog_adopted_bindings"] = adopted
        snapshot = json.dumps(record).encode()
    _write(path, snapshot)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        files = [
            path.resolve()
            for name in ("description", "saved_diff", "snapshot", "rename_map", "secrets_file")
            if (path := getattr(args, name, None))
        ]
        if len(files) != len(set(files)):
            raise EngineError(
                [{"code": "file_conflict", "message": "Choose a different file for each argument and try again."}]
            )
        if args.command == "diff" and args.saved_diff:
            # A failed diff must not leave a previous diff ready to push under the requested filename.
            _write(args.saved_diff, b"")
        credentials: Credentials = {
            "api_key": os.environ.get("POSTHOG_API_KEY", ""),
            "host": args.host,
            "project_id": args.project_id,
        }
        if not credentials["api_key"]:
            raise EngineError(
                [
                    {
                        "code": "credentials_missing",
                        "message": "Set POSTHOG_API_KEY to a personal API key for this project and try again.",
                    }
                ]
            )
        options: EngineOptions = {"allow_registry": args.allow_registry}
        if args.timeout_seconds is not None:
            options["timeout_seconds"] = args.timeout_seconds
        if binary := os.getenv("POSTHOG_STACK_BINARY"):
            options["binary"] = binary
        if args.mirror:
            options["mirror"] = args.mirror
        if args.rename_map:
            renames = json.loads(args.rename_map.read_bytes())
            if not isinstance(renames, dict):
                raise ValueError
            options["rename_map"] = renames
        if getattr(args, "secrets_file", None):
            secrets = json.loads(args.secrets_file.read_bytes())
            if not isinstance(secrets, dict) or not all(isinstance(value, str) for value in secrets.values()):
                raise ValueError
            credentials["secrets"] = secrets

        raw_description = json.loads(args.description.read_bytes())
        if not isinstance(raw_description, dict):
            raise ValueError
        description = cast(StackDescription, raw_description)
        with TemporaryDirectory() as workdir:
            if args.command == "diff":
                previous, bindings = _read_snapshot(args.snapshot)
                engine_input = translate_in(description, bindings, options)
                diff, saved, _ = run_diff(workdir, engine_input, previous, credentials)
                if saved and args.saved_diff:
                    _write(args.saved_diff, saved)
                sys.stdout.write(json.dumps(diff, ensure_ascii=False) + "\n")
                if diff["errors"]:
                    return 1
                return 2 if diff["changes"] or diff["drift"] else 0

            if not args.snapshot:
                raise EngineError(
                    [
                        {
                            "code": "snapshot_missing",
                            "message": "Choose a private file with --snapshot to save this stack's bindings.",
                        }
                    ]
                )
            with _snapshot_lock(args.snapshot):
                previous, bindings = _read_snapshot(args.snapshot)
                engine_input = translate_in(description, bindings, options)
                result, snapshot = run_push(workdir, engine_input, args.saved_diff.read_bytes(), previous, credentials)
                if snapshot and snapshot != previous:
                    _write_snapshot(args.snapshot, snapshot, result["bindings"])
            sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
            return 1 if result["errors"] else 0
    except EngineError as exc:
        errors = exc.errors
    except (OSError, ValueError, KeyError, TypeError):
        errors = [{"code": "input_invalid", "message": "Check the files and their permissions, then try again."}]
    sys.stderr.write(json.dumps({"errors": errors}) + "\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
