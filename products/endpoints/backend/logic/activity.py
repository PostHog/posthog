import dataclasses
from typing import Optional

from posthog.models.activity_logging.activity_log import ActivityContextBase


@dataclasses.dataclass(frozen=True)
class EndpointContext(ActivityContextBase):
    id: Optional[int] = None
    version: Optional[int] = None
