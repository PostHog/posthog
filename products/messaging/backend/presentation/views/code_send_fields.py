import re
import base64
from collections.abc import Mapping
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.settings import api_settings

from posthog.dataclasses import frozen

from products.messaging.backend.facade.transactional_email import PIPELINE_ADDRESS_PATTERN

MAX_ADDRESSES_PER_FIELD = 10
MAX_ATTACHMENTS = 10
MAX_ATTACHMENTS_BYTES = 512 * 1024
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


class EmailAttachmentSerializer(serializers.Serializer):
    filename = serializers.CharField(
        max_length=255,
        help_text="File name the recipient sees, such as `invoice.pdf`. No path and no line breaks. A file type "
        "mailbox providers block, such as `.exe`, is refused.",
    )
    content = serializers.CharField(
        trim_whitespace=False,
        help_text="The file's bytes as standard base64, without line breaks.",
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
                    {unknown: "An attachment takes `filename`, `content`, `content_type` and `content_id`."},
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

    def validate_content(self, content: str) -> str:
        if not _decoded_size(content):
            raise serializers.ValidationError("The content is empty.", code="empty_attachment")
        return content

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


def _decoded_size(content: str) -> int:
    try:
        return len(base64.b64decode(content, validate=True))
    except ValueError:
        raise serializers.ValidationError("The content isn't valid base64.", code="not_base64") from None


class AttachmentListField(serializers.ListField):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            child=EmailAttachmentSerializer(),
            max_length=MAX_ATTACHMENTS,
            error_messages={"max_length": "Send at most {max_length} attachments."},
            **kwargs,
        )

    def to_internal_value(self, data: Any) -> list[dict[str, str]]:
        attachments = super().to_internal_value(data)
        if sum(_decoded_size(attachment["content"]) for attachment in attachments) > MAX_ATTACHMENTS_BYTES:
            raise serializers.ValidationError(
                f"Send at most {MAX_ATTACHMENTS_BYTES // 1024} KB of attachments in total, counted after decoding.",
                code="attachments_too_large",
            )
        return attachments


@frozen
class _Reason:
    why: str
    fix: str


_ADDRESS_REASON = _Reason(
    why="PostHog sends a copy to every address in `cc` and `bcc`, so each one must be a single address.",
    fix="Send one address or a list of up to 10 bare addresses, such as `jane@example.com`.",
)
_ATTACHMENT_REASON = _Reason(
    why="PostHog attaches each file as it is sent, so each one needs a file name and base64 content.",
    fix="Send each attachment as `{filename, content}`, with `content` in base64.",
)
_ATTACHMENT_LIMIT_REASON = _Reason(
    why="A transactional email has to arrive fast, and large attachments slow its delivery.",
    fix=f"Send at most {MAX_ATTACHMENTS} files and {MAX_ATTACHMENTS_BYTES // 1024} KB in total, or link to "
    "larger files from the email body.",
)
_COPY_LIMIT_REASON = _Reason(
    why="A transactional email goes to one recipient, with copies for a few others.",
    fix=f"Send at most {MAX_ADDRESSES_PER_FIELD} addresses in each of `cc` and `bcc`. To reach more people, send "
    "each one their own email.",
)
_LIST_LIMIT_REASONS = {"cc": _COPY_LIMIT_REASON, "bcc": _COPY_LIMIT_REASON, "attachments": _ATTACHMENT_LIMIT_REASON}
_REASONS_BY_CODE = {
    "not_base64": _Reason(
        why="Attachment content travels as base64 text inside the JSON body.",
        fix="Encode the file as standard base64, without line breaks.",
    ),
    "empty_attachment": _Reason(
        why="An empty file gives the recipient nothing to open.", fix="Leave out the empty file."
    ),
    "blocked_file_type": _Reason(
        why="Mailbox providers refuse emails that carry files that can run code, so the email would bounce.",
        fix="Send a different file type, or link to the file from the email body.",
    ),
    "attachments_too_large": _ATTACHMENT_LIMIT_REASON,
    "max_length": _Reason(
        why="PostHog puts the file name, MIME type and content ID into the email's headers, and takes at most 255 "
        "characters for each.",
        fix="Shorten the value to 255 characters or fewer.",
    ),
    "unsafe_filename": _Reason(
        why="The file name goes into the email's headers, where a path or a line break could change the email.",
        fix="Send only the file name, such as `invoice.pdf`.",
    ),
    "not_mime_type": _Reason(
        why="The MIME type goes into the email's headers, so it must be a type and a subtype only.",
        fix="Send a type such as `application/pdf`, or leave `content_type` out.",
    ),
    "unsafe_content_id": _Reason(
        why="The Content-ID header wraps the ID in angle brackets, so brackets inside the ID break the `cid:` "
        "reference from the HTML.",
        fix="Send the bare ID, such as `logo`, and reference it as `cid:logo` in the HTML.",
    ),
    "field_not_accepted": _Reason(
        why="This PostHog version doesn't take the field yet, so it refused the email instead of sending it "
        "without it.",
        fix="Send the email without this field, or send it again once PostHog takes the field.",
    ),
    "template_key_only": _Reason(
        why="A send with `template_id` takes its recipients and content from the template.",
        fix="Send the email's content with `template_key`, or leave this field out.",
    ),
}


def field_not_accepted_refusal(field: str) -> serializers.ValidationError:
    return serializers.ValidationError(
        {field: "PostHog doesn't take this field yet, so it didn't send the email."}, code="field_not_accepted"
    )


def template_send_refusal(field: str) -> serializers.ValidationError:
    return serializers.ValidationError(
        {field: "Only a send with `template_key` takes this field."}, code="template_key_only"
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
    else:
        reason = _REASONS_BY_CODE.get(code, _ADDRESS_REASON if path[0] in ADDRESS_FIELDS else _ATTACHMENT_REASON)
    attr = "__".join(path)
    return {
        **body,
        "type": "invalid_request",
        "code": "invalid_request",
        "attr": attr,
        "why": reason.why,
        "fix": reason.fix,
    }
