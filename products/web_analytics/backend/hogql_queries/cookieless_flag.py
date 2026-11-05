from typing import TYPE_CHECKING, Optional

from posthog.cloud_utils import is_cloud

if TYPE_CHECKING:
    from posthog.models import Team


def resolve_cookieless_traffic_is_regular_modifier(team: "Team", current: Optional[bool]) -> Optional[bool]:
    from posthog.models.team.team import CookielessServerHashMode  # noqa: PLC0415 - keeps models off this import path

    # The exemption trusts the `cookielessd_` prefix of `$device_id`, which any client can send.
    # Ingestion drops cookieless events for a team with cookieless disabled, so on such a team a
    # prefixed device ID is forged and must not exempt the event.
    if team.cookieless_server_hash_mode in (None, CookielessServerHashMode.DISABLED):
        return False
    # The default must not depend on the process. Precompute puts this value in its job
    # hash, so a process that resolves it differently (for example one without local flag
    # definitions) builds jobs that no other process reads.
    if current is not None:
        return current
    if not is_cloud():
        return None
    return True
