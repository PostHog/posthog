import hashlib
from io import BytesIO

from django.conf import settings

from PIL import Image

from posthog.models import Team, User
from posthog.models.uploaded_media import (
    MEDIA_PURPOSE_EMAIL,
    ObjectStorageUnavailable,
    UploadedMedia,
    sniff_image_content_type,
)

_MIN_LOGO_SIDE_PX = 128
_EMAIL_LOGO_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


def email_logo_content_type(body: bytes) -> str | None:
    content_type = sniff_image_content_type(body)
    if content_type not in _EMAIL_LOGO_EXTENSIONS:
        return None
    with Image.open(BytesIO(body)) as decoded:
        return content_type if max(decoded.size) >= _MIN_LOGO_SIDE_PX else None


def store_email_logo(body: bytes, content_type: str, team: Team, user: User) -> str | None:
    if not settings.OBJECT_STORAGE_ENABLED:
        return None
    file_name = f"email-logo-{hashlib.sha256(body).hexdigest()[:16]}.{_EMAIL_LOGO_EXTENSIONS[content_type]}"
    stored = UploadedMedia.objects.filter(
        team_id=team.id, purpose=MEDIA_PURPOSE_EMAIL, file_name=file_name, pending=False, media_location__isnull=False
    ).first()
    if stored is None:
        stored = _save_logo(body, content_type, file_name, team, user)
    return stored.get_absolute_url() if stored else None


def _save_logo(body: bytes, content_type: str, file_name: str, team: Team, user: User) -> UploadedMedia | None:
    try:
        media = UploadedMedia.save_content(
            team=team,
            created_by=user,
            file_name=file_name,
            content_type=content_type,
            content=body,
            purpose=MEDIA_PURPOSE_EMAIL,
        )
    except ObjectStorageUnavailable:
        return None
    if media is not None:
        media.size_bytes = len(body)
        media.save(update_fields=["size_bytes"])
    return media
