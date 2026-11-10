from collections.abc import Mapping
from typing import Any, cast

from django.core.exceptions import RequestDataTooBig

import structlog
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ErrorDetail
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings

from posthog.api.fields import LengthFirstListField
from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.event_usage import groups
from posthog.permissions import is_authenticated_via_project_secret_api_key
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle

from products.messaging.backend.facade.transactional_email import (
    AttachmentUploadRequest,
    AttachmentUploadSlot,
    AttachmentUploadStatus,
    AttachmentUploadTarget,
    DeliveryUnavailable,
    FieldNotAccepted,
    InvalidRequest,
    MessageTooLarge,
    UploadQuotaExceeded,
    prepare_attachment_uploads,
)
from products.messaging.backend.presentation.views.code_send_fields import (
    MAX_ATTACHMENTS,
    MESSAGE_LIMIT,
    MESSAGE_TOO_LARGE_REASON,
    SHA256_HEX,
    TOO_MANY_FILES_REASON,
    Reason,
)
from products.messaging.backend.presentation.views.message_templates import (
    TRANSACTIONAL_EMAIL_SEND_SCOPE,
    require_email_from_code,
    transactional_email_authorized_by,
)
from products.messaging.backend.presentation.views.refusals import ExplainedRefusal, RequestBodyCapMixin, request_cap

logger = structlog.get_logger(__name__)

SIZE_CONFLICT = "size_conflict"


class AttachmentUploadFileSerializer(serializers.Serializer):
    sha256 = serializers.RegexField(
        SHA256_HEX,
        help_text="SHA-256 of the file's bytes, as 64 lowercase hex characters. PostHog stores the file under it.",
    )
    size = serializers.IntegerField(min_value=1, help_text="Size of the file in bytes.")

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, Mapping):
            unknown = next((key for key in sorted(data) if key not in self.fields), None)
            if unknown is not None:
                raise serializers.ValidationError({unknown: "A file takes only `sha256` and `size`."})
        return super().to_internal_value(data)


class AttachmentUploadsRequestSerializer(serializers.Serializer):
    files = LengthFirstListField(
        child=AttachmentUploadFileSerializer(),
        min_length=1,
        max_length=MAX_ATTACHMENTS,
        help_text=f"The files one email will carry: 1 to {MAX_ATTACHMENTS}, at most {MESSAGE_LIMIT} for the "
        "whole email.",
    )

    def validate_files(self, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        size_of: dict[str, int] = {}
        for index, file in enumerate(files):
            if size_of.setdefault(file["sha256"], file["size"]) != file["size"]:
                raise serializers.ValidationError(
                    {
                        str(index): {
                            "size": [
                                ErrorDetail(
                                    "Another file in this list has the same SHA-256 and a different size.",
                                    code=SIZE_CONFLICT,
                                )
                            ]
                        }
                    }
                )
        return files


class AttachmentUploadSlotSerializer(serializers.Serializer):
    sha256 = serializers.CharField(help_text="SHA-256 of the file, as sent.")
    status = serializers.ChoiceField(
        choices=AttachmentUploadStatus.choices,
        help_text="`present` when PostHog already has the file and nothing needs uploading, `upload` when the file "
        "must be uploaded to `url` before the send.",
    )
    expires_at = serializers.DateTimeField(
        required=False,
        help_text="For a `present` file: when PostHog deletes it unless a send uses it before then.",
    )
    url = serializers.URLField(
        required=False,
        help_text="For an `upload` file: where to send the file's bytes, without your PostHog API key.",
    )
    method = serializers.CharField(required=False, help_text="For an `upload` file: the HTTP method, `PUT`.")
    headers = serializers.DictField(
        child=serializers.CharField(),
        required=False,
        help_text="For an `upload` file: the headers to send with the bytes, exactly as given. The upload is "
        "refused if the bytes don't match the size or SHA-256.",
    )
    url_expires_at = serializers.DateTimeField(
        required=False, help_text="For an `upload` file: when `url` stops accepting the upload."
    )


class AttachmentUploadsResponseSerializer(serializers.Serializer):
    files = AttachmentUploadSlotSerializer(many=True, help_text="One answer per requested file, in request order.")


_FILE_LIST_REASON = Reason(
    why="The request names the files one email will carry, so PostHog can tell which to upload.",
    fix=f"Send `files` as a list of 1 to {MAX_ATTACHMENTS} objects, each `{{sha256, size}}`.",
)
_FILE_FIELD_REASONS = {
    "sha256": Reason(
        why="PostHog stores each file under its SHA-256, so the hash names the file.",
        fix="Send the SHA-256 of the file's bytes as 64 lowercase hex characters.",
    ),
    "size": Reason(
        why="PostHog signs each upload for the file's exact size, and an empty file gives the recipient nothing "
        "to open.",
        fix="Send the file's size in bytes, at least 1.",
    ),
}
_UNKNOWN_FILE_FIELD_REASON = Reason(
    why="A file is named by its SHA-256 and size. Its name and type go on the send.",
    fix="Send each file as `{sha256, size}`.",
)
_BODY_REASON = Reason(
    why="The request body is a JSON object with a `files` list.",
    fix='Send `{"files": [{"sha256": ..., "size": ...}]}`.',
)
_SIZE_CONFLICT_REASON = Reason(
    why="Files with the same SHA-256 have the same bytes, so they have one size.",
    fix="Send each file's exact size in bytes, or list the file once.",
)


def with_upload_reason(body: dict[str, Any]) -> dict[str, Any]:
    path = [part for part in (body.get("attr") or "").split("__") if part]
    if path and path[-1] == api_settings.NON_FIELD_ERRORS_KEY:
        path.pop()
    if body.get("type") != "validation_error" or (path and path[0] != "files"):
        return body
    code = "invalid_request"
    if not path:
        reason = _BODY_REASON
    elif len(path) == 1 and body.get("code") == "max_length":
        code, reason = "too_many_attachments", TOO_MANY_FILES_REASON
    elif body.get("code") == SIZE_CONFLICT:
        reason = _SIZE_CONFLICT_REASON
    elif len(path) == 3:
        reason = _FILE_FIELD_REASONS.get(path[2], _UNKNOWN_FILE_FIELD_REASON)
    else:
        reason = _FILE_LIST_REASON
    return {
        **body,
        "type": "invalid_request",
        "code": code,
        "attr": "__".join(path) or None,
        "why": reason.why,
        "fix": reason.fix,
    }


def _attachments_not_accepted() -> ExplainedRefusal:
    return ExplainedRefusal(
        "This project can't send files yet, so PostHog didn't prepare the uploads.",
        code="field_not_accepted",
        attr="files",
        why="Sending files isn't available to this project yet.",
        fix="Send the email without files, or try again once files are available to this project.",
    )


def _message_too_large(attr: str | None) -> ExplainedRefusal:
    return ExplainedRefusal(
        "These files are too large for one email, so PostHog didn't prepare the uploads.",
        code="message_too_large",
        attr=attr,
        why=MESSAGE_TOO_LARGE_REASON.why,
        fix=MESSAGE_TOO_LARGE_REASON.fix,
    )


def _files_the_pipeline_refused() -> ExplainedRefusal:
    return ExplainedRefusal(
        "PostHog's email pipeline refused this file list, so PostHog didn't prepare the uploads.",
        code="invalid_request",
        attr="files",
        why="The email pipeline checks each file's SHA-256 and size, and one of them didn't pass.",
        fix="List each file once, as `{sha256, size}` with its exact size in bytes, then send the request again.",
    )


def _upload_quota_exceeded() -> ExplainedRefusal:
    return ExplainedRefusal(
        "This project uploaded as many file bytes as it can today, so PostHog didn't prepare the uploads.",
        code="upload_quota_exceeded",
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        why="Each project can upload a limited number of file bytes per day, counted in UTC.",
        fix="Send files this project already uploaded, which don't count, or upload again after midnight UTC.",
    )


def _storage_unavailable() -> ExplainedRefusal:
    return ExplainedRefusal(
        "File storage didn't answer, so PostHog didn't prepare the uploads.",
        code="delivery_unavailable",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        why="PostHog couldn't check its file storage for these files.",
        fix="Send the same request again shortly.",
    )


def _upload_body_too_large() -> ExplainedRefusal:
    return ExplainedRefusal(
        f"The request body is over {request_cap()}, so PostHog didn't prepare the uploads.",
        code="content_too_large",
        why=f"PostHog reads at most {request_cap()} of request body, so it refused the request without reading it.",
        fix="Send each file as its `sha256` and `size` only. The file's bytes go to the upload `url` PostHog answers.",
    )


class KeyOrMemberRateThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    def allow_request(self, request: Any, view: Any) -> bool:
        return self._allow_request_internal(request, view, personal_api_key_only=False)


class AttachmentUploadBurstThrottle(KeyOrMemberRateThrottle):
    scope = "transactional_email_attachment_upload_burst"
    rate = "600/minute"


class AttachmentUploadSustainedThrottle(KeyOrMemberRateThrottle):
    scope = "transactional_email_attachment_upload_sustained"
    rate = "20000/hour"


class AttachmentUploadTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "transactional_email_attachment_upload_psak_team_burst"
    rate = "600/minute"


class AttachmentUploadTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "transactional_email_attachment_upload_psak_team_sustained"
    rate = "20000/hour"


class MessagingAttachmentsViewSet(RequestBodyCapMixin, TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "hog_flow"
    permission_classes = [IsAuthenticated]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["uploads"]
    records_have_object_access_rules = False
    _upload_reported = False

    def get_throttles(self):
        return [
            AttachmentUploadBurstThrottle(),
            AttachmentUploadSustainedThrottle(),
            AttachmentUploadTeamBurstThrottle(),
            AttachmentUploadTeamSustainedThrottle(),
        ]

    def body_too_large(self) -> ExplainedRefusal:
        return _upload_body_too_large()

    def handle_exception(self, exc: Exception) -> Response:
        body_read = not isinstance(exc, RequestDataTooBig)
        if not body_read:
            exc = self.refuse_body_over_the_cap()
        response = super().handle_exception(exc)
        if isinstance(response.data, dict):
            response.data = with_upload_reason(response.data)
        if isinstance(exc, ExplainedRefusal):
            exc.explain(response)
        if not self._upload_reported and isinstance(exc, exceptions.ValidationError | ExplainedRefusal):
            self._report_upload(
                self._requested(self.request.data if body_read else None),
                outcome="rejected",
                error_code=response.data.get("code"),
            )
        return response

    @validated_request(
        AttachmentUploadsRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=AttachmentUploadsResponseSerializer,
                description="Each file is present, or comes with where to upload it",
            ),
            400: OpenApiResponse(
                description="A file is malformed, there are more than 10, they're too large for one email, or the "
                "project can't send files yet"
            ),
            429: OpenApiResponse(description="Rate limited, or the project uploaded its daily limit of file bytes"),
            503: OpenApiResponse(description="File storage didn't answer. Send the same request again"),
        },
        summary="Prepare attachment uploads",
        description=(
            "Before sending an email with files, ask where to upload each one. Name each file by the SHA-256 of its "
            "bytes and its size. A file this project already uploaded answers `present` and needs no upload. Any "
            "other file answers `upload`: PUT its bytes to `url` with exactly the `headers` given and without your "
            "PostHog API key, before `url_expires_at`. Once every upload succeeded, send the email with the files' "
            "hashes in `attachments`. Needs the `transactional_email:write` scope."
        ),
    )
    @action(detail=False, methods=["POST"], required_scopes=[TRANSACTIONAL_EMAIL_SEND_SCOPE])
    def uploads(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        require_email_from_code(self.team)
        files = [AttachmentUploadRequest(**file) for file in request.validated_data["files"]]
        requested = self._requested(request.validated_data)
        try:
            slots = prepare_attachment_uploads(self.team, files)
        except FieldNotAccepted:
            raise _attachments_not_accepted() from None
        except MessageTooLarge as e:
            raise _message_too_large(self._size_attr(files, e.largest_file_sha256)) from None
        except UploadQuotaExceeded:
            raise _upload_quota_exceeded() from None
        except InvalidRequest:
            raise _files_the_pipeline_refused() from None
        except DeliveryUnavailable:
            self._report_upload(requested, outcome="unavailable", error_code="delivery_unavailable")
            raise _storage_unavailable() from None
        upload_bytes = sum(file.size for file, slot in zip(files, slots) if isinstance(slot, AttachmentUploadTarget))
        self._report_upload(
            requested,
            outcome="answered",
            upload_bytes=upload_bytes,
            present_bytes=sum(file.size for file in files) - upload_bytes,
        )
        return Response(AttachmentUploadsResponseSerializer({"files": cast(list[AttachmentUploadSlot], slots)}).data)

    @staticmethod
    def _size_attr(files: list[AttachmentUploadRequest], sha256: str | None) -> str | None:
        index = next((index for index, file in enumerate(files) if file.sha256 == sha256), None)
        return "files" if index is None else f"files__{index}__size"

    @staticmethod
    def _requested(body: Any) -> dict[str, int | None]:
        files = body.get("files") if isinstance(body, Mapping) else None
        if not isinstance(files, list):
            return {"file_count": None, "requested_bytes": None}
        sizes = [file.get("size") if isinstance(file, Mapping) else None for file in files]
        known = all(isinstance(size, int) and not isinstance(size, bool) for size in sizes)
        return {"file_count": len(files), "requested_bytes": sum(cast(list[int], sizes)) if known else None}

    def _report_upload(self, requested: dict[str, int | None], **outcome: Any) -> None:
        self._upload_reported = True
        try:
            posthoganalytics.capture(
                distinct_id=self.request.user.distinct_id,
                event="transactional email attachments upload",
                properties={
                    "team_id": self.team_id,
                    "auth_method": "project_secret_api_key"
                    if is_authenticated_via_project_secret_api_key(self.request)
                    else "user",
                    "authorized_by": transactional_email_authorized_by(self.request, TRANSACTIONAL_EMAIL_SEND_SCOPE),
                    "upload_bytes": None,
                    "present_bytes": None,
                    "error_code": None,
                    **requested,
                    **outcome,
                },
                groups=groups(self.organization, self.team),
            )
        except Exception as e:
            logger.warning("Failed to capture transactional email attachments upload event", error=str(e))
