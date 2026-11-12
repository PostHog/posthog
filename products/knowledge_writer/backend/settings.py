from posthog.dataclasses import frozen
from posthog.settings.utils import get_from_env

from .feature_flags import is_writer_enabled

DEFAULT_DOCS_PATHS = "contents/docs/"
DEFAULT_DOCS_SITEMAP_URL = "https://posthog.com/sitemap/sitemap-0.xml"


@frozen
class WriterSettings:
    team_id: int
    user_id: int
    docs_repository: str
    source_repositories: tuple[str, ...]
    docs_paths: tuple[str, ...]


@frozen
class DocsSource:
    docs_repository: str
    sitemap_url: str
    docs_url_prefix: str


def docs_source() -> DocsSource | None:
    docs_repository = get_from_env("KNOWLEDGE_WRITER_DOCS_REPOSITORY", optional=True)
    if not docs_repository:
        return None
    return docs_source_for(docs_repository)


def docs_source_for(docs_repository: str) -> DocsSource:
    sitemap_url = get_from_env("KNOWLEDGE_WRITER_DOCS_SITEMAP_URL", DEFAULT_DOCS_SITEMAP_URL)
    sitemap_origin = "/".join(sitemap_url.split("/", 3)[:3])
    return DocsSource(
        docs_repository=docs_repository,
        sitemap_url=sitemap_url,
        docs_url_prefix=get_from_env("KNOWLEDGE_WRITER_DOCS_URL_PREFIX", f"{sitemap_origin}/docs/"),
    )


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
