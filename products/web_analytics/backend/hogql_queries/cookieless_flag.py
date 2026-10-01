from typing import TYPE_CHECKING, Optional

from posthog.cloud_utils import is_cloud

if TYPE_CHECKING:
    from posthog.models import Team


def resolve_cookieless_traffic_is_regular_modifier(team: "Team", current: Optional[bool]) -> Optional[bool]:
    # The default must not depend on the process. Precompute puts this value in its job
    # hash, so a process that resolves it differently (for example one without local flag
    # definitions) builds jobs that no other process reads.
    if current is not None:
        return current
    if not is_cloud():
        return None
    return True
