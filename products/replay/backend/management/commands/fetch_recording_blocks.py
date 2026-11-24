import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

import snappy
import requests

from products.replay.backend.management.commands.recording_api_token import mint_for_this_pod

REQUEST_TIMEOUT_SECONDS = 60


class Command(BaseCommand):
    help = "Save one recording's blocks from recording-api as JSONL files, from a claimed toolbox pod."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--session-id", required=True)
        parser.add_argument("--reason", required=True, help="For example the support ticket. recording-api logs it.")
        parser.add_argument("--out", help="Directory to write to. Defaults to /tmp/recording-<team_id>-<session_id>.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        session_id: str = options["session_id"]
        out = Path(options["out"] or f"/tmp/recording-{team_id}-{session_id}")
        token = mint_for_this_pod(team_id, options["reason"]).token

        base = (
            f"{settings.RECORDING_API_URL.rstrip('/')}/api/projects/{team_id}/recordings/{quote(session_id, safe='')}"
        )
        with requests.Session() as session:
            # The egress proxy in HTTP_PROXY refuses in-cluster hosts, so this session ignores it.
            session.trust_env = False
            session.headers["Authorization"] = f"Bearer {token}"
            blocks = _get(session, f"{base}/blocks").json().get("blocks", [])
            if not blocks:
                raise CommandError(f"recording-api lists no blocks for session {session_id} in team {team_id}.")

            out.mkdir(parents=True, exist_ok=True)
            index = []
            for number, block in enumerate(blocks):
                entry = {
                    "file": None,
                    "start_timestamp": block.get("start_timestamp"),
                    "end_timestamp": block.get("end_timestamp"),
                }
                if ref := block.get("ref"):
                    path = out / f"{number:04d}.jsonl"
                    path.write_bytes(snappy.decompress(_get(session, f"{base}/blocks/{quote(ref, safe='')}").content))
                    entry["file"] = path.name
                index.append(entry)

        (out / "index.json").write_text(json.dumps(index, indent=2))
        missing = sum(1 for entry in index if entry["file"] is None)
        self.stdout.write(json.dumps({"out": str(out), "blocks": len(index), "without_ref": missing}))
        if missing:
            self.stderr.write(
                f"{missing} blocks have no ref, because they were written before encryption, so they were skipped."
            )


def _get(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code != 200:
        raise CommandError(f"recording-api answered {response.status_code} for {url}: {response.text[:200]}")
    return response
