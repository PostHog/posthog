from posthog.dataclasses import frozen
from posthog.settings.utils import get_from_env

from .feature_flags import is_writer_enabled

DEFAULT_DOCS_PATHS = "contents/docs/"


@frozen
class WriterSettings:
    team_id: int
    user_id: int
    docs_repository: str
    source_repositories: tuple[str, ...]
    docs_paths: tuple[str, ...]


def comma_separated(listed: str) -> tuple[str, ...]:
    return tuple(name.strip() for name in listed.split(",") if name.strip())


def source_repositories() -> tuple[str, ...]:
    return comma_separated(get_from_env("KNOWLEDGE_WRITER_SOURCE_REPOSITORIES", ""))


def docs_paths() -> tuple[str, ...]:
    listed = comma_separated(get_from_env("KNOWLEDGE_WRITER_DOCS_PATHS", DEFAULT_DOCS_PATHS))
    return tuple(docs_path.rstrip("/") for docs_path in listed)


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
        docs_paths=docs_paths(),
    )
