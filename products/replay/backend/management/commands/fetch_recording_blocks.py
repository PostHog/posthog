import os
import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

import snappy
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from products.replay.backend.management.commands.recording_api_token import mint_for_this_pod

REQUEST_TIMEOUT_SECONDS = 60
# A fresh token replaces one this close to expiry, so a long recording outlives the 15-minute token.
TOKEN_REFRESH_MARGIN = timedelta(minutes=2)
MISSING_REF_CAUSES = "recorded before encryption, or recording-api could not read the session key, so a retry may help"


class Command(BaseCommand):
    help = "Save one recording's blocks from recording-api as JSONL files, from a claimed toolbox pod."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--session-id", required=True)
        parser.add_argument("--reason", required=True, help="For example the support ticket. recording-api logs it.")
        parser.add_argument(
            "--out",
            help="Directory to create and write to. It must not exist yet. Defaults to a new private directory under /tmp.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        session_id: str = options["session_id"]
        if "/" in session_id or "\\" in session_id or session_id.startswith("."):
            raise CommandError("--session-id must not contain a slash or start with a dot.")

        with _private_directory(options["out"], prefix=f"recording-{team_id}-{session_id}-") as (out, out_fd):
            reader = _BlockReader(team_id, session_id, options["reason"])
            blocks = reader.list_blocks()
            index = []
            for number, block in enumerate(blocks):
                entry = {
                    "file": None,
                    "start_timestamp": block.get("start_timestamp"),
                    "end_timestamp": block.get("end_timestamp"),
                }
                if ref := block.get("ref"):
                    name = f"{number:04d}.jsonl"
                    try:
                        _write_new_file(out_fd, name, snappy.decompress(reader.read_block(ref)))
                    except (CommandError, snappy.UncompressError) as error:
                        raise CommandError(
                            f"Block {number} failed, so {out} holds only the blocks before it: {error}"
                        ) from error
                    entry["file"] = name
                index.append(entry)
            _write_new_file(out_fd, "index.json", json.dumps(index, indent=2).encode())

        missing = sum(1 for entry in index if entry["file"] is None)
        self.stdout.write(json.dumps({"out": str(out), "blocks": len(index), "without_ref": missing}))
        if missing:
            self.stderr.write(f"Skipped {missing} blocks without a ref: {MISSING_REF_CAUSES}.")


@contextmanager
def _private_directory(path: str | None, prefix: str) -> Iterator[tuple[Path, int]]:
    """Create a new owner-only directory and yield an open handle to it, removing it again if nothing was written."""
    if path:
        out = Path(path)
        try:
            out.mkdir(mode=0o700)
        except FileExistsError as error:
            raise CommandError(f"{out} already exists. Pick a new path for --out.") from error
        except OSError as error:
            raise CommandError(f"Could not create {out}: {error}") from error
    else:
        out = Path(tempfile.mkdtemp(prefix=prefix))
    # Writes go through this handle rather than the path, so renaming or replacing the path cannot redirect them.
    out_fd = os.open(out, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        yield out, out_fd
    except BaseException:
        if not os.listdir(out_fd):
            out.rmdir()
        raise
    finally:
        os.close(out_fd)


def _write_new_file(dir_fd: int, name: str, data: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
    with os.fdopen(fd, "wb") as file:
        file.write(data)


class _BlockReader:
    """Reads one recording's blocks from recording-api with a staff token it keeps fresh."""

    def __init__(self, team_id: int, session_id: str, reason: str) -> None:
        self.team_id = team_id
        self.reason = reason
        self.base = (
            f"{settings.RECORDING_API_URL.rstrip('/')}/api/projects/{team_id}/recordings/{quote(session_id, safe='')}"
        )
        self.session = requests.Session()
        # The egress proxy in HTTP_PROXY refuses in-cluster hosts, so this session ignores it.
        self.session.trust_env = False
        # recording-api answers 503 with Retry-After when its read budget is spent, so busy replies are retried.
        retry = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        self.session.mount(settings.RECORDING_API_URL, HTTPAdapter(max_retries=retry))
        self.expires_at = datetime.min.replace(tzinfo=UTC)

    def list_blocks(self) -> list[dict[str, Any]]:
        try:
            blocks = self._get(f"{self.base}/blocks").json()["blocks"]
        except (ValueError, KeyError, TypeError) as error:
            raise CommandError(f"recording-api sent a block listing this command cannot read: {error}") from error
        if not blocks:
            raise CommandError("recording-api lists no blocks for this session.")
        if not any(block.get("ref") for block in blocks):
            raise CommandError(f"None of the {len(blocks)} blocks has a ref: {MISSING_REF_CAUSES}.")
        return blocks

    def read_block(self, ref: str) -> bytes:
        return self._get(f"{self.base}/blocks/{quote(ref, safe='')}").content

    def _get(self, url: str) -> requests.Response:
        if self.expires_at - datetime.now(tz=UTC) < TOKEN_REFRESH_MARGIN:
            staff_token = mint_for_this_pod(self.team_id, self.reason)
            self.session.headers["Authorization"] = f"Bearer {staff_token.token}"
            self.expires_at = staff_token.expires_at
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as error:
            raise CommandError(f"Could not reach recording-api at {url}: {error}") from error
        if response.status_code != 200:
            raise CommandError(f"recording-api answered {response.status_code} for {url}: {response.text[:200]}")
        return response
