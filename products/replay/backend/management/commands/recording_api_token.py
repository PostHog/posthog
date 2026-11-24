import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

import structlog

from posthog.models.team.team import Team
from posthog.session_recordings.recordings.recording_api_jwt import (
    StaffRecordingApiToken,
    mint_recording_api_staff_token,
    staff_key_problem,
)

logger = structlog.get_logger(__name__)

# The chart mounts the pod's labels here, and the toolbox claim script labels the pod with the claimer's SSO email.
POD_LABELS_PATH = Path("/etc/podinfo/labels")
CLAIM_LABEL = "toolbox-claimed"

USAGE = """\
To save a whole recording, `fetch_recording_blocks` does all of this for you.
List the blocks, then fetch each one by the ref the listing gives it. --noproxy skips the egress proxy, which refuses in-cluster hosts:
  curl --noproxy '*' -H "Authorization: Bearer $TOKEN" "$URL/api/projects/<team_id>/recordings/<session_id>/blocks"
  curl --noproxy '*' -H "Authorization: Bearer $TOKEN" "$URL/api/projects/<team_id>/recordings/<session_id>/blocks/<ref>" -o block
A block is snappy-compressed JSONL; python -c "import snappy,sys;sys.stdout.buffer.write(snappy.decompress(open('block','rb').read()))"
Recordings from before encryption have no refs, so they cannot be read this way.
"""


def claimed_by() -> str | None:
    """The claim label of this toolbox pod, as the claim script wrote it, or None when the pod is unclaimed."""
    try:
        lines = POD_LABELS_PATH.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        key, _, quoted = line.partition("=")
        if key == CLAIM_LABEL:
            # Kept as written, because turning the claim script's `_at_` back into `@` cannot be done without loss.
            value = json.loads(quoted)
            return value if isinstance(value, str) and value else None
    return None


def mint_for_this_pod(team_id: int, reason: str) -> StaffRecordingApiToken:
    """Mint a staff token naming this pod's claimer, or raise CommandError saying why the pod cannot."""
    reason = reason.strip()
    if not reason:
        raise CommandError("--reason must not be empty.")
    actor = claimed_by()
    if actor is None:
        raise CommandError("This pod has no toolbox claim, so the token would name nobody. Claim it first.")
    if problem := staff_key_problem():
        raise CommandError(f"{problem}, so this pod cannot mint tokens.")
    if not settings.RECORDING_API_URL:
        raise CommandError("RECORDING_API_URL is not set on this pod.")
    if not Team.objects.filter(pk=team_id).exists():
        raise CommandError(f"No team has ID {team_id}.")

    staff_token = mint_recording_api_staff_token(team_id, actor, reason)
    logger.info("recording_api_staff_token_minted", team_id=team_id, actor=actor, reason=reason)
    return staff_token


class Command(BaseCommand):
    help = (
        "Mint a short-lived, read-only recording-api token for one team, to read recording blocks from a toolbox pod."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--reason", required=True, help="For example the support ticket. recording-api logs it.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        staff_token = mint_for_this_pod(team_id, options["reason"])
        self.stdout.write(
            json.dumps(
                {
                    "token": staff_token.token,
                    "url": settings.RECORDING_API_URL.rstrip("/"),
                    "team_id": team_id,
                    "expires_at": staff_token.expires_at.isoformat(),
                }
            )
        )
        self.stderr.write(USAGE)
