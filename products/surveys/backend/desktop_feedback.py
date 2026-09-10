from collections.abc import Mapping
from typing import Any

from django.core.files.uploadedfile import UploadedFile

import structlog

from posthog.api.uploaded_media import sniff_image_content_type
from posthog.models import Team, UploadedMedia, User
from posthog.ph_client import PH_EU_API_KEY, PH_US_API_KEY, get_client
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.utils import get_instance_region

FEEDBACK_SURVEY_ID = "019ee235-2e3b-0000-64b3-5f2efa487452"
FEEDBACK_SURVEY_QUESTION_ID = "68648b23-caaf-4080-ae5f-051513d3097f"
FEEDBACK_SURVEY_SOURCE_QUESTION_ID = "e4560a6b-3eab-4c61-a731-8d0c10dd1b7d"

logger = structlog.get_logger(__name__)

MEDIA_PROPERTY_BY_FIELD = {
    "screenshot": "feedback_screenshot_url",
    "image_1": "feedback_image_1_url",
    "image_2": "feedback_image_2_url",
}


class DesktopFeedbackUnavailable(Exception):
    pass


def _discard_media(media: UploadedMedia) -> None:
    media.pending = True
    media.save(update_fields=["pending"])
    try:
        if media.media_location:
            object_storage.delete(media.media_location)
    except ObjectStorageError:
        logger.warning(
            "desktop_feedback.media_cleanup_failed",
            media_id=str(media.id),
            exc_info=True,
        )
        return
    media.delete()


def _save_media(*, user: User, files: Mapping[str, UploadedFile]) -> tuple[dict[str, str], list[UploadedMedia]]:
    if not files:
        return {}, []

    try:
        media_api_key = PH_EU_API_KEY if get_instance_region() == "EU" else PH_US_API_KEY
        media_team = Team.objects.get(api_token=media_api_key)
    except Team.DoesNotExist as error:
        raise DesktopFeedbackUnavailable("Feedback attachments are unavailable on this PostHog instance") from error

    uploaded: list[UploadedMedia] = []
    try:
        for file in files.values():
            content = file.read()
            content_type = sniff_image_content_type(content)
            if content_type is None:
                raise DesktopFeedbackUnavailable("Feedback attachment is not a valid image")

            media = UploadedMedia.save_content(
                team=media_team,
                created_by=user,
                file_name=file.name or "desktop-feedback-image",
                content_type=content_type,
                content=content,
            )
            if media is None:
                raise DesktopFeedbackUnavailable("Could not store feedback attachment")
            uploaded.append(media)
            media.size_bytes = len(content)
            media.save(update_fields=["size_bytes"])
    except Exception:
        for media in uploaded:
            _discard_media(media)
        raise

    return (
        {
            MEDIA_PROPERTY_BY_FIELD[field_name]: media.get_absolute_url()
            for field_name, media in zip(files.keys(), uploaded, strict=True)
        },
        uploaded,
    )


def _capture_feedback_event(*, user: User, properties: dict[str, Any]) -> str:
    client = get_client(
        "US",
        sync_mode=True,
        capture_mode="v1",
        timeout=5,
        max_retries=2,
    )
    if client is None:
        raise DesktopFeedbackUnavailable("Feedback capture is unavailable")
    try:
        event_uuid = client.capture(
            "survey sent",
            distinct_id=str(user.uuid),
            properties=properties,
        )
        if event_uuid is None:
            raise DesktopFeedbackUnavailable("Feedback event was not accepted")
        return event_uuid
    finally:
        client.shutdown()


def submit_desktop_feedback(
    *,
    user: User,
    data: Mapping[str, Any],
    files: Mapping[str, UploadedFile],
) -> str:
    media_properties, uploaded_media = _save_media(user=user, files=files)
    properties: dict[str, Any] = {
        "$survey_id": FEEDBACK_SURVEY_ID,
        "$survey_questions": [
            {"id": FEEDBACK_SURVEY_QUESTION_ID},
            {"id": FEEDBACK_SURVEY_SOURCE_QUESTION_ID},
        ],
        f"$survey_response_{FEEDBACK_SURVEY_QUESTION_ID}": data["response"],
        f"$survey_response_{FEEDBACK_SURVEY_SOURCE_QUESTION_ID}": data["source"],
        "feedback_view": data["feedback_view"],
        **media_properties,
    }
    optional_properties = {
        "feedback_task_id": data.get("feedback_task_id"),
        "feedback_folder_id": data.get("feedback_folder_id"),
        "feedback_app_logs": data.get("feedback_app_logs"),
        "app_version": data.get("app_version"),
        "$session_id": str(data["session_id"]) if data.get("session_id") else None,
    }
    properties.update({key: value for key, value in optional_properties.items() if value})

    try:
        return _capture_feedback_event(user=user, properties=properties)
    except Exception:
        for media in uploaded_media:
            _discard_media(media)
        raise
