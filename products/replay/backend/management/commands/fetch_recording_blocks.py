import json
import tempfile
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
            "--out", help="Empty directory to write to. Defaults to a new private directory under /tmp."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        session_id: str = options["session_id"]
        reason: str = options["reason"]
        if "/" in session_id or "\\" in session_id or session_id.startswith("."):
            raise CommandError("--session-id must not contain a slash or start with a dot.")
        out = Path(options["out"]) if options["out"] else None
        if out and out.exists() and any(out.iterdir()):
            raise CommandError(f"{out} is not empty, so its files could mix with this recording. Pick another --out.")

        base = (
            f"{settings.RECORDING_API_URL.rstrip('/')}/api/projects/{team_id}/recordings/{quote(session_id, safe='')}"
        )
        with requests.Session() as session:
            # The egress proxy in HTTP_PROXY refuses in-cluster hosts, so this session ignores it.
            session.trust_env = False
            # recording-api answers 503 with Retry-After when its read budget is spent, so busy replies are retried.
            retry = Retry(
                total=5,
                backoff_factor=1,
                status_forcelist=(429, 502, 503, 504),
                allowed_methods=("GET",),
                respect_retry_after_header=True,
                raise_on_status=False,
            )
            session.mount(settings.RECORDING_API_URL, HTTPAdapter(max_retries=retry))
            expires_at = datetime.min.replace(tzinfo=UTC)

            def get(url: str) -> requests.Response:
                nonlocal expires_at
                if expires_at - datetime.now(tz=UTC) < TOKEN_REFRESH_MARGIN:
                    staff_token = mint_for_this_pod(team_id, reason)
                    session.headers["Authorization"] = f"Bearer {staff_token.token}"
                    expires_at = staff_token.expires_at
                try:
                    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
                except requests.RequestException as error:
                    raise CommandError(f"Could not reach recording-api at {url}: {error}") from error
                if response.status_code != 200:
                    raise CommandError(
                        f"recording-api answered {response.status_code} for {url}: {response.text[:200]}"
                    )
                return response

            try:
                blocks = get(f"{base}/blocks").json()["blocks"]
            except (ValueError, KeyError, TypeError) as error:
                raise CommandError(f"recording-api sent a block listing this command cannot read: {error}") from error
            if not blocks:
                raise CommandError(f"recording-api lists no blocks for session {session_id} in team {team_id}.")
            if not any(block.get("ref") for block in blocks):
                raise CommandError(f"None of the {len(blocks)} blocks has a ref: {MISSING_REF_CAUSES}.")

            # The blocks are decrypted customer recordings, so other users on the pod must not read them.
            if out is None:
                # mkdtemp picks an unguessable name, so no other user can create the directory first.
                out = Path(tempfile.mkdtemp(prefix=f"recording-{team_id}-{session_id}-"))
            else:
                out.mkdir(parents=True, exist_ok=True)
                out.chmod(0o700)
            index = []
            for number, block in enumerate(blocks):
                entry = {
                    "file": None,
                    "start_timestamp": block.get("start_timestamp"),
                    "end_timestamp": block.get("end_timestamp"),
                }
                if ref := block.get("ref"):
                    path = out / f"{number:04d}.jsonl"
                    try:
                        path.write_bytes(snappy.decompress(get(f"{base}/blocks/{quote(ref, safe='')}").content))
                    except (CommandError, snappy.UncompressError) as error:
                        raise CommandError(
                            f"Block {number} failed, so {out} holds only the blocks before it: {error}"
                        ) from error
                    entry["file"] = path.name
                index.append(entry)

        (out / "index.json").write_text(json.dumps(index, indent=2))
        missing = sum(1 for entry in index if entry["file"] is None)
        self.stdout.write(json.dumps({"out": str(out), "blocks": len(index), "without_ref": missing}))
        if missing:
            self.stderr.write(f"Skipped {missing} blocks without a ref: {MISSING_REF_CAUSES}.")
