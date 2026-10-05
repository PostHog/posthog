from urllib.parse import quote

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.models import Team, UploadedMedia, User
from posthog.models.github_integration_base import GitHubInstallationUnavailable, GitHubIntegrationError
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.integration.github import GitHubFileTooLarge
from posthog.models.uploaded_media import (
    MAX_IMAGE_BYTES,
    MEDIA_PURPOSE_EMAIL,
    RejectedImage,
    verified_image_content_type,
)

from products.workflows.backend.services.email_brand_detection import (
    GITHUB_SOURCE,
    REQUEST_TIMEOUT_SECONDS,
    UNREADABLE_STATUS_CODES,
    GitHubBusy,
    GitHubDisconnected,
    RepositoryUnreadable,
)
from products.workflows.backend.services.ico import largest_ico_frame_as_png

SVG_MARKER = b"<svg"


class LogoNotFound(Exception):
    pass


class LogoStorageFailed(Exception):
    pass


@frozen
class ImportedLogo:
    media: UploadedMedia


@frozen
class SvgLogo:
    """An SVG logo the browser has to draw as PNG, because the server has no SVG rasterizer."""

    markup: str


def import_repository_logo(
    *, team: Team, user: User, integration: Integration, repository: str, path: str
) -> ImportedLogo | SvgLogo:
    """Store a repository image in the email media library, converting an ICO to a PNG of its largest frame.

    Raises ``LogoNotFound``, ``RejectedImage``, ``GitHubBusy``, ``GitHubDisconnected``, ``RepositoryUnreadable``,
    ``ObjectStorageUnavailable`` and ``LogoStorageFailed``.
    """
    content = _read_logo(integration, repository, path)
    if path.lower().endswith(".svg"):
        return SvgLogo(markup=_svg_markup(content))
    return ImportedLogo(media=_store(team, user, _email_ready_image(path, content)))


def _read_logo(integration: Integration, repository: str, path: str) -> bytes:
    github = GitHubIntegration(integration, source=GITHUB_SOURCE, priority=Priority.NORMAL)
    try:
        content = github.get_file_bytes(
            repository,
            quote(path, safe="/"),
            max_size=MAX_IMAGE_BYTES,
            timeout=REQUEST_TIMEOUT_SECONDS,
            retry_transient=False,
        )
    except GitHubFileTooLarge as error:
        raise RejectedImage.too_large() from error
    except GitHubInstallationUnavailable as error:
        raise GitHubDisconnected() from error
    except GitHubIntegrationError as error:
        if error.status_code in UNREADABLE_STATUS_CODES:
            raise RepositoryUnreadable() from error
        raise GitHubBusy() from error
    except (GitHubEgressBudgetExhausted, GitHubRateLimitError) as error:
        raise GitHubBusy() from error
    if content is None:
        raise LogoNotFound()
    return content


def _svg_markup(content: bytes) -> str:
    if SVG_MARKER not in content.lower():
        raise RejectedImage.invalid()
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RejectedImage.invalid() from error


@frozen
class _EmailImage:
    file_name: str
    content: bytes
    content_type: str


def _email_ready_image(path: str, content: bytes) -> _EmailImage:
    file_name = path.rsplit("/", 1)[-1]
    png = largest_ico_frame_as_png(content)
    if png is not None:
        file_name, content = f"{file_name.rsplit('.', 1)[0]}.png", png
    return _EmailImage(file_name=file_name, content=content, content_type=verified_image_content_type(content))


def _store(team: Team, user: User, image: _EmailImage) -> UploadedMedia:
    media = UploadedMedia.save_content(
        team=team,
        created_by=user,
        file_name=image.file_name,
        content_type=image.content_type,
        content=image.content,
        purpose=MEDIA_PURPOSE_EMAIL,
    )
    if media is None:
        raise LogoStorageFailed()
    media.size_bytes = len(image.content)
    media.save(update_fields=["size_bytes"])
    return media
