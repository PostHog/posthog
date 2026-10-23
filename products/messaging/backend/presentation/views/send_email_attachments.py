"""Files a code send attaches to its email, held to what fits in the email queue and what mailbox providers accept."""

import re
import base64
import binascii
from typing import Any

from rest_framework import serializers

MAX_ATTACHMENTS = 10
MAX_ATTACHMENTS_BYTES = 512 * 1024
MAX_FILENAME_LENGTH = 255
MAX_CONTENT_TYPE_LENGTH = 255
MAX_CONTENT_ID_LENGTH = 128

CONTENT_TYPE = re.compile(r"[!-~]+/[!-~]+(;[ -~]*)?")
CONTENT_ID = re.compile(r"[!-;=?-~]+")
FILENAME_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f/\\]")

# The file types the email provider refuses to send: https://docs.aws.amazon.com/ses/latest/dg/attachments.html
BLOCKED_EXTENSIONS = frozenset(
    """
    ade adp app asp bas bat cer chm cmd com cpl crt csh der exe fxp gadget hlp hta inf ins isp its js jse ksh lib lnk
    mad maf mag mam maq mar mas mat mau mav maw mda mdb mde mdt mdw mdz msc msh msh1 msh2 mshxml msh1xml msh2xml msi
    msp mst ops pcd pif plg prf prg ps1 ps1xml ps2 ps2xml psc1 psc2 reg scf scr sct shb shs sys tmp url vb vbe vbs vps
    vsmacros vss vst vsw vxd ws wsc wsf wsh xnk
    """.split()
)


class EmailAttachmentSerializer(serializers.Serializer):
    filename = serializers.CharField(
        max_length=MAX_FILENAME_LENGTH,
        help_text="File name the recipient sees, such as `invite.ics`. No paths, and no file types mailbox "
        "providers block, such as `.exe`.",
    )
    content = serializers.CharField(help_text="The file content, Base64 encoded.")
    content_type = serializers.CharField(
        required=False,
        max_length=MAX_CONTENT_TYPE_LENGTH,
        help_text="MIME type with its parameters, such as `text/calendar; method=REQUEST`. Without it, the type "
        "follows the file name.",
    )
    content_id = serializers.CharField(
        required=False,
        max_length=MAX_CONTENT_ID_LENGTH,
        help_text='Shows the file inline: reference it in `html` as `<img src="cid:logo">` with `content_id` `logo`.',
    )

    def validate_content(self, value: str) -> bytes:
        try:
            return base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise serializers.ValidationError("Send the file content as Base64.") from None

    def validate_filename(self, value: str) -> str:
        if FILENAME_FORBIDDEN.search(value):
            raise serializers.ValidationError("Use a file name without paths or line breaks, such as `invite.ics`.")
        name = value.rstrip(". ")
        extension = name.rpartition(".")[2].lower() if "." in name else ""
        if extension in BLOCKED_EXTENSIONS:
            raise serializers.ValidationError(
                f"Mailbox providers block `.{extension}` files. Send a link to the file instead."
            )
        return value

    def validate_content_type(self, value: str) -> str:
        if not CONTENT_TYPE.fullmatch(value):
            raise serializers.ValidationError("Use a MIME type, such as `application/pdf`, on one line.")
        return value

    def validate_content_id(self, value: str) -> str:
        if not CONTENT_ID.fullmatch(value):
            raise serializers.ValidationError("Use visible ASCII characters without `<` or `>`, such as `logo`.")
        return value


def validate_attachments(attachments: list[dict[str, Any]]) -> None:
    if sum(len(attachment["content"]) for attachment in attachments) > MAX_ATTACHMENTS_BYTES:
        raise serializers.ValidationError(
            f"Attachments can hold {MAX_ATTACHMENTS_BYTES // 1024}KB in total. Send a link to larger files."
        )


def attachments_field() -> serializers.ListField:
    return serializers.ListField(
        child=EmailAttachmentSerializer(),
        required=False,
        max_length=MAX_ATTACHMENTS,
        validators=[validate_attachments],
        help_text=f"Files to attach, at most {MAX_ATTACHMENTS} and {MAX_ATTACHMENTS_BYTES // 1024}KB in total after "
        "decoding. Not with `template.id`.",
    )
