import json
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

import structlog

from posthog.models.team.team import Team
from posthog.session_recordings.recordings.recording_api_jwt import mint_recording_api_staff_token, staff_key_problem

logger = structlog.get_logger(__name__)

USAGE = """\
List the blocks, then fetch one with a key and byte range from that list:
  curl -H "Authorization: Bearer $TOKEN" "$URL/api/projects/<team_id>/recordings/<session_id>/blocks"
  curl -H "Authorization: Bearer $TOKEN" \\
    "$URL/api/projects/<team_id>/recordings/<session_id>/block?key=<key>&start_byte=<start>&end_byte=<end>&decompress=true"
"""


class Command(BaseCommand):
    help = (
        "Mint a short-lived, read-only recording-api token for one team, to read recording blocks from a toolbox pod."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--actor", required=True, help="Your email. recording-api logs it on every request.")
        parser.add_argument("--reason", required=True, help="For example the support ticket. recording-api logs it.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        actor: str = options["actor"].strip()
        reason: str = options["reason"].strip()
        if not actor or not reason:
            raise CommandError("--actor and --reason must not be empty.")
        if problem := staff_key_problem():
            raise CommandError(f"{problem}, so this pod cannot mint tokens.")
        if not settings.RECORDING_API_URL:
            raise CommandError("RECORDING_API_URL is not set on this pod.")
        if not Team.objects.filter(pk=team_id).exists():
            raise CommandError(f"No team has ID {team_id}.")

        staff_token = mint_recording_api_staff_token(team_id, actor, reason)
        logger.info("recording_api_staff_token_minted", team_id=team_id, actor=actor, reason=reason)
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
