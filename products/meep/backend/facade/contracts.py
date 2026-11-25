from datetime import datetime
from uuid import UUID

from posthog.dataclasses import frozen


@frozen
class TopicDetails:
    id: UUID
    title: str
    mission: str
    conversation_id: UUID | None
    created_at: datetime


@frozen
class FileData:
    contents: bytes
    revision: int
    competing_with: int | None
