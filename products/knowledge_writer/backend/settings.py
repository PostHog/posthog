from posthog.dataclasses import frozen
from posthog.settings.utils import get_from_env

from .feature_flags import is_writer_enabled


@frozen
class WriterSettings:
    team_id: int
    user_id: int
    docs_repository: str
    source_repositories: tuple[str, ...]


def source_repositories() -> tuple[str, ...]:
    listed = get_from_env("KNOWLEDGE_WRITER_SOURCE_REPOSITORIES", "")
    return tuple(name.strip() for name in listed.split(",") if name.strip())


def configured_writer_team_id() -> int | None:
    return get_from_env("KNOWLEDGE_WRITER_TEAM_ID", optional=True, type_cast=int)


def writer_settings() -> WriterSettings | None:
    team_id = configured_writer_team_id()
    user_id = get_from_env("KNOWLEDGE_WRITER_USER_ID", optional=True, type_cast=int)
    docs_repository = get_from_env("KNOWLEDGE_WRITER_DOCS_REPOSITORY", optional=True)
    if team_id is None or user_id is None or not docs_repository:
        return None
    if not is_writer_enabled(team_id):
        return None
    return WriterSettings(
        team_id=team_id,
        user_id=user_id,
        docs_repository=docs_repository,
        source_repositories=source_repositories(),
    )
