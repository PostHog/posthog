import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from django.utils import timezone

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.settings import api_settings
from rest_framework.utils import html

from posthog.api.fields import LengthFirstListField
from posthog.dataclasses import frozen

from products.messaging.backend.facade.transactional_email import (
    PIPELINE_ADDRESS_PATTERN,
    AttachmentNotUploaded,
    EmailTracking,
    MessageTooLarge,
)
from products.messaging.backend.presentation.views.refusals import ExplainedRefusal

MAX_ADDRESSES_PER_FIELD = 10
MAX_ATTACHMENTS = 10
MESSAGE_LIMIT = "40 MB after Base64 encoding, about 29 MB of files"
SHA256_HEX = r"^[0-9a-f]{64}$"
UPLOAD_ROUTE = "POST /api/projects/{project_id}/messaging/attachments/uploads/"
MAX_FILENAME_LENGTH = 255
SES_ATTACHMENT_HEADER_MAX_LENGTH = 78
BLOCKED_ATTACHMENT_EXTENSIONS = frozenset(
    {
        "ade", "adp", "apk", "app", "appx", "appxbundle", "asp", "bas", "bat", "cab", "cer", "chm", "cmd", "com", "cpl",
        "crt", "csh", "der", "diagcab", "diagcfg", "diagpkg", "dll", "dmg", "ex", "ex_", "exe", "fxp", "gadget", "hlp",
        "hta", "img", "inf", "ins", "iso", "isp", "its", "jar", "jnlp", "js", "jse", "ksh", "lib", "lnk", "mad", "maf",
        "mag", "mam", "maq", "mar", "mas", "mat", "mau", "mav", "maw", "mda", "mdb", "mde", "mdt", "mdw", "mdz", "mjs",
        "msc", "msh", "msh1", "msh1xml", "msh2", "msh2xml", "mshxml", "msi", "msix", "msixbundle", "msp", "mst", "nsh",
        "ops", "pcd", "pif", "plg", "prf", "prg", "ps1", "ps1xml", "ps2", "ps2xml", "psc1", "psc2", "reg", "scf", "scr",
        "sct", "shb", "shs", "sys", "tmp", "url", "vb", "vbe", "vbs", "vhd", "vps", "vsmacros", "vss", "vst", "vsw",
        "vxd", "ws", "wsc", "wsf", "wsh", "xll", "xnk",
    }
)  # fmt: skip
MIME_TYPE_WITHOUT_PARAMETERS = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}"
)
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")

ADDRESS_FIELDS = ("cc", "bcc")
CODE_SEND_EXTRA_FIELDS = (*ADDRESS_FIELDS, "attachments")


def validate_pipeline_address(address: str) -> None:
    if not PIPELINE_ADDRESS_PATTERN.fullmatch(address):
        raise serializers.ValidationError(
            "Enter an address PostHog can send to, like jane@example.com. Quoted names, IP addresses and "
            "non-ASCII domains aren't supported."
        )


def _extension_as_windows_saves_it(filename: str) -> str | None:
    _, dot, extension = filename.rstrip(". ").rpartition(".")
    return extension.lower() if dot else None


class ScheduledAtField(serializers.DateTimeField):
    default_error_messages = {
        "no_offset": "Add a timezone offset to the time, such as `Z` or `+02:00`, so PostHog knows when to send it."
    }

    def enforce_timezone(self, value: datetime) -> datetime:
        if timezone.is_naive(value):
            self.fail("no_offset")
        return super().enforce_timezone(value)


@extend_schema_field(
    {
        "oneOf": [
            {"type": "string", "format": "email"},
            {
                "type": "array",
                "items": {"type": "string", "format": "email"},
                "maxItems": MAX_ADDRESSES_PER_FIELD,
            },
        ]
    }
)
class AddressListField(serializers.ListField):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            child=serializers.EmailField(validators=[validate_pipeline_address]),
            max_length=MAX_ADDRESSES_PER_FIELD,
            error_messages={"max_length": "Send at most {max_length} addresses."},
            **kwargs,
        )

    def to_internal_value(self, data: Any) -> list[str]:
        return super().to_internal_value([data] if isinstance(data, str) else data)


TRACKING_KINDS = ("opens", "clicks", "engagement")


@extend_schema_field(
    {
        "oneOf": [
            {"type": "boolean"},
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "opens": {
                        "type": "boolean",
                        "description": "Whether PostHog adds its open pixel to the email. Defaults to true.",
                    },
                    "clicks": {
                        "type": "boolean",
                        "description": "Whether the email's links go through a redirect that counts clicks. "
                        "Defaults to true when the email isn't sensitive and false when it is. Needs `opens`. A link with "
                        "`data-ph-no-track` keeps its own address.",
                    },
                    "engagement": {
                        "type": "boolean",
                        "description": "Whether the email's engagement events (sent, delivered, opened, clicked, "
                        "bounced) are captured as analytics events of the recipient. Defaults to true.",
                    },
                },
            },
        ]
    }
)
class EmailTrackingField(serializers.Field):
    default_error_messages = {
        "unknown_kind": "`tracking` takes `opens`, `clicks` and `engagement`.",
        "clicks_need_opens": "Click tracking needs open tracking. Turn on `opens`, or turn off `clicks`.",
    }

    def to_internal_value(self, data: Any) -> EmailTracking:
        if isinstance(data, Mapping):
            if any(kind not in TRACKING_KINDS for kind in data):
                self.fail("unknown_kind")
            tracking = EmailTracking(
                **{kind: serializers.BooleanField().to_internal_value(on) for kind, on in data.items()}
            )
        else:
            on = serializers.BooleanField().to_internal_value(data)
            tracking = EmailTracking(opens=on, clicks=on, engagement=on)
        if tracking.clicks and not tracking.opens:
            self.fail("clicks_need_opens")
        return tracking

    def to_representation(self, value: EmailTracking) -> dict[str, bool | None]:
        return {"opens": value.opens, "clicks": value.clicks, "engagement": value.engagement}


class EmailAttachmentSerializer(serializers.Serializer):
    sha256 = serializers.RegexField(
        SHA256_HEX,
        help_text=f"SHA-256 of a file uploaded through `{UPLOAD_ROUTE}`, as 64 lowercase hex characters.",
    )
    filename = serializers.CharField(
        max_length=MAX_FILENAME_LENGTH,
        help_text="File name the recipient sees, such as `invoice.pdf`. No path and no line breaks. A file type "
        "mailbox providers block, such as `.exe`, is refused.",
    )
    content_type = serializers.CharField(
        required=False,
        max_length=SES_ATTACHMENT_HEADER_MAX_LENGTH,
        help_text="MIME type of the file, such as `application/pdf`. Without it, the type follows from the file name.",
    )
    content_id = serializers.CharField(
        required=False,
        max_length=SES_ATTACHMENT_HEADER_MAX_LENGTH,
        help_text="Content ID that the HTML body references as `cid:<content_id>` to show the file inline, such as "
        "`logo`. Without `<` or `>`.",
    )

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, Mapping):
            unknown = next((key for key in sorted(data) if key not in self.fields), None)
            if unknown is not None:
                raise serializers.ValidationError(
                    {unknown: "An attachment takes `sha256`, `filename`, `content_type` and `content_id`."},
                    code="unknown_attachment_field",
                )
        return super().to_internal_value(data)

    def validate_filename(self, filename: str) -> str:
        if "/" in filename or "\\" in filename or CONTROL_CHARACTERS.search(filename):
            raise serializers.ValidationError(
                "Use a file name with no path separator and no line break.", code="unsafe_filename"
            )
        extension = _extension_as_windows_saves_it(filename)
        if extension in BLOCKED_ATTACHMENT_EXTENSIONS:
            raise serializers.ValidationError(
                f"Mailbox providers block `.{extension}` files.", code="blocked_file_type"
            )
        return filename

    def validate_content_type(self, content_type: str) -> str:
        if not MIME_TYPE_WITHOUT_PARAMETERS.fullmatch(content_type):
            raise serializers.ValidationError("Enter a MIME type, such as `application/pdf`.", code="not_mime_type")
        return content_type

    def validate_content_id(self, content_id: str) -> str:
        if "<" in content_id or ">" in content_id or CONTROL_CHARACTERS.search(content_id):
            raise serializers.ValidationError(
                "Send the content ID without `<`, `>` or line breaks.", code="unsafe_content_id"
            )
        return content_id


@frozen
class AttachmentSize:
    count: int | None
    bytes: int | None


def attachment_size(body: Any) -> AttachmentSize:
    # A form body spreads each file over keys such as `attachments[0]sha256`, so its files can't be counted from it.
    if not isinstance(body, Mapping) or html.is_html_input(body):
        return AttachmentSize(count=None, bytes=None)
    attachments = body.get("attachments")
    if attachments is None or attachments == []:
        return AttachmentSize(count=0, bytes=0)
    if not isinstance(attachments, list):
        return AttachmentSize(count=None, bytes=None)
    # Only the CDP service knows the sizes of uploaded files, so its answer to the send fills in the bytes.
    return AttachmentSize(count=len(attachments), bytes=None)


class AttachmentListField(LengthFirstListField):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            child=EmailAttachmentSerializer(),
            max_length=MAX_ATTACHMENTS,
            error_messages={"max_length": "Send at most {max_length} attachments."},
            **kwargs,
        )


@frozen
class Reason:
    why: str
    fix: str


_ADDRESS_REASON = Reason(
    why="PostHog sends a copy to every address in `cc` and `bcc`, so each one must be a single address.",
    fix="Send one address or a list of up to 10 bare addresses, such as `jane@example.com`.",
)
_ATTACHMENT_REASON = Reason(
    why="PostHog attaches files you uploaded first, each named by its SHA-256 and given a file name.",
    fix=f"Upload each file through `{UPLOAD_ROUTE}`, then send it as `{{sha256, filename}}`.",
)
_SHA256_REASON = Reason(
    why="PostHog stores each uploaded file under its SHA-256, so the hash names the file.",
    fix="Send the SHA-256 of the file's bytes as 64 lowercase hex characters, as you sent it to the upload.",
)
_INLINE_CONTENT_REASON = Reason(
    why="PostHog attaches only uploaded files, and the send names each one by its SHA-256.",
    fix=f"Upload the file through `{UPLOAD_ROUTE}`, then send it as `{{sha256, filename}}` without `content`.",
)
TOO_MANY_FILES_REASON = Reason(
    why=f"An email carries at most {MAX_ATTACHMENTS} files.",
    fix=f"Name at most {MAX_ATTACHMENTS} files, and link to any others from the email body.",
)
MESSAGE_TOO_LARGE_REASON = Reason(
    why="PostHog's email provider takes emails up to 40 MB, and Base64 encoding makes each file about a third larger.",
    fix=f"Keep the email under {MESSAGE_LIMIT}: send fewer or smaller files, or link to large files from the "
    "email body.",
)
_COPY_LIMIT_REASON = Reason(
    why="A transactional email goes to one recipient, with copies for a few others.",
    fix=f"Send at most {MAX_ADDRESSES_PER_FIELD} addresses in each of `cc` and `bcc`. To reach more people, send "
    "each one their own email.",
)
_HEADER_LENGTH_REASONS = {
    field: Reason(
        why=f"PostHog puts `{field}` into the email's headers, which take at most {limit} characters for it.",
        fix=f"Shorten `{field}` to {limit} characters or fewer.",
    )
    for field, limit in (
        ("filename", MAX_FILENAME_LENGTH),
        ("content_type", SES_ATTACHMENT_HEADER_MAX_LENGTH),
        ("content_id", SES_ATTACHMENT_HEADER_MAX_LENGTH),
    )
}
_LIST_LIMIT_REASONS = {"cc": _COPY_LIMIT_REASON, "bcc": _COPY_LIMIT_REASON, "attachments": TOO_MANY_FILES_REASON}
_REASONS_BY_CODE = {
    "blocked_file_type": Reason(
        why="Mailbox providers refuse emails that carry files that can run code, so the email would bounce.",
        fix="Send a different file type, or link to the file from the email body.",
    ),
    "unsafe_filename": Reason(
        why="The file name goes into the email's headers, where a path or a line break could change the email.",
        fix="Send only the file name, such as `invoice.pdf`.",
    ),
    "not_mime_type": Reason(
        why="The MIME type goes into the email's headers, so it must be a type and a subtype only.",
        fix="Send a type such as `application/pdf`, or leave `content_type` out.",
    ),
    "unsafe_content_id": Reason(
        why="The Content-ID header wraps the ID in angle brackets, so brackets inside the ID break the `cid:` "
        "reference from the HTML.",
        fix="Send the bare ID, such as `logo`, and reference it as `cid:logo` in the HTML.",
    ),
    "field_not_accepted": Reason(
        why="This PostHog version doesn't take the field yet, so it refused the email instead of sending it "
        "without it.",
        fix="Send the email without this field, or send it again once PostHog takes the field.",
    ),
    "template_key_only": Reason(
        why="A send with `template_id` takes its recipients and content from the template.",
        fix="Send the email's content with `template_key`, or leave this field out.",
    ),
}


def refused_attachment(
    error: AttachmentNotUploaded | MessageTooLarge, attachments: list[dict[str, Any]]
) -> ExplainedRefusal:
    sha256 = error.sha256 if isinstance(error, AttachmentNotUploaded) else error.largest_file_sha256
    index = next((i for i, file in enumerate(attachments) if file["sha256"] == sha256), None)
    attr = "attachments" if index is None else f"attachments__{index}__sha256"
    if isinstance(error, AttachmentNotUploaded):
        return ExplainedRefusal(
            "A file this email names isn't uploaded, so PostHog didn't send the email.",
            code="attachment_not_uploaded",
            attr=attr,
            why="This project has no uploaded file with this SHA-256. Its upload didn't finish, it expired, or it "
            "went to another project.",
            fix=f"Upload the file through `{UPLOAD_ROUTE}` and wait for its upload to succeed, then send again.",
        )
    return ExplainedRefusal(
        "These files make the email larger than PostHog can send, so it didn't send the email.",
        code="message_too_large",
        attr=attr,
        why=MESSAGE_TOO_LARGE_REASON.why,
        fix=MESSAGE_TOO_LARGE_REASON.fix,
    )


def field_not_accepted_refusal(field: str) -> serializers.ValidationError:
    return serializers.ValidationError(
        {field: "PostHog doesn't take this field yet, so it didn't send the email."}, code="field_not_accepted"
    )


def template_send_refusal(field: str) -> serializers.ValidationError:
    return serializers.ValidationError(
        {field: "Only a send with `template_key` takes this field."}, code="template_key_only"
    )


# An SDK tells these refusals apart by their code. Any other refusal of these fields answers `invalid_request`.
_OWN_CODES = frozenset(
    {
        "too_many_attachments",
        "blocked_file_type",
        "unsafe_filename",
        "not_mime_type",
        "unsafe_content_id",
        "field_not_accepted",
    }
)


def with_code_send_reason(body: dict[str, Any]) -> dict[str, Any]:
    path, code = (body.get("attr") or "").split("__"), str(body.get("code") or "")
    if body.get("type") != "validation_error" or (
        path[0] not in CODE_SEND_EXTRA_FIELDS and code != "field_not_accepted"
    ):
        return body
    if path[-1] == api_settings.NON_FIELD_ERRORS_KEY:
        path.pop()
    if code == "max_length" and len(path) == 1:
        reason = _LIST_LIMIT_REASONS[path[0]]
        code = "too_many_attachments" if path[0] == "attachments" else code
    elif code == "max_length" and path[-1] in _HEADER_LENGTH_REASONS:
        reason = _HEADER_LENGTH_REASONS[path[-1]]
    elif path[0] == "attachments" and path[-1] == "sha256":
        reason = _SHA256_REASON
    elif code == "unknown_attachment_field" and path[-1] == "content":
        reason = _INLINE_CONTENT_REASON
    else:
        reason = _REASONS_BY_CODE.get(code, _ADDRESS_REASON if path[0] in ADDRESS_FIELDS else _ATTACHMENT_REASON)
    attr = "__".join(path)
    return {
        **body,
        "type": "invalid_request",
        "code": code if code in _OWN_CODES else "invalid_request",
        "attr": attr,
        "why": reason.why,
        "fix": reason.fix,
    }
