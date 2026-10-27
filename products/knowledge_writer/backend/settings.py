from posthog.dataclasses import frozen
from posthog.settings.utils import get_from_env


@frozen
class WriterSettings:
    team_id: int
    user_id: int
    docs_repository: str


def writer_settings() -> WriterSettings | None:
    team_id = get_from_env("KNOWLEDGE_WRITER_TEAM_ID", optional=True, type_cast=int)
    user_id = get_from_env("KNOWLEDGE_WRITER_USER_ID", optional=True, type_cast=int)
    docs_repository = get_from_env("KNOWLEDGE_WRITER_DOCS_REPOSITORY", optional=True)
    if team_id is None or user_id is None or not docs_repository:
        return None
    return WriterSettings(team_id=team_id, user_id=user_id, docs_repository=docs_repository)
