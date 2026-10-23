"""The copies, headers and tags a code send sets on its own email, with the limits the email provider holds them to."""

import re
from typing import Any

from rest_framework import serializers

MAX_COPIES = 10
MAX_HEADERS = 10
MAX_TAGS = 10
MAX_HEADER_NAME_LENGTH = 126
MAX_HEADER_VALUE_LENGTH = 870
MAX_TAG_LENGTH = 256

# A bare address with none of the characters that would let one entry of a comma-separated list name a second one.
PLAIN_ADDRESS = re.compile(r"[^\s@\"<>,;:()\[\]\\]+@[^\s@\"<>,;:()\[\]\\]+\.[^\s@\"<>,;:()\[\]\\]+")
HEADER_NAME = re.compile(r"[!-9;-~]+")
HEADER_VALUE = re.compile(r"[ -~]*")
TAG_PART = re.compile(r"[A-Za-z0-9_-]+")
RESERVED_TAG_PREFIX = "ph_"

HEADERS_POSTHOG_SETS = frozenset(
    {
        "auto-submitted",
        "bcc",
        "cc",
        "date",
        "dkim-signature",
        "from",
        "message-id",
        "mime-version",
        "received",
        "reply-to",
        "return-path",
        "sender",
        "subject",
        "to",
    }
)
HEADER_PREFIXES_POSTHOG_SETS = ("content-", "x-posthog-", "x-ses-")


def plain_address(value: str) -> None:
    if not PLAIN_ADDRESS.fullmatch(value):
        raise serializers.ValidationError(f"`{value}` is not a bare address. Send it as `jane@example.com`.")


class PlainAddressField(serializers.EmailField):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.validators.append(plain_address)


def copies_field(*, help_text: str) -> serializers.ListField:
    return serializers.ListField(child=PlainAddressField(), required=False, max_length=MAX_COPIES, help_text=help_text)


class EmailTagSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=MAX_TAG_LENGTH,
        help_text="Tag name: ASCII letters, numbers, `_` and `-`. Names starting with `ph_` are PostHog's.",
    )
    value = serializers.CharField(
        max_length=MAX_TAG_LENGTH, help_text="Tag value: ASCII letters, numbers, `_` and `-`."
    )

    def validate_name(self, value: str) -> str:
        if not TAG_PART.fullmatch(value):
            raise serializers.ValidationError("Use only ASCII letters, numbers, `_` and `-`.")
        if value.lower().startswith(RESERVED_TAG_PREFIX):
            raise serializers.ValidationError(f"Names starting with `{RESERVED_TAG_PREFIX}` are PostHog's. Rename it.")
        return value

    def validate_value(self, value: str) -> str:
        if not TAG_PART.fullmatch(value):
            raise serializers.ValidationError("Use only ASCII letters, numbers, `_` and `-`.")
        return value


def validate_headers(headers: dict[str, str]) -> None:
    if len(headers) > MAX_HEADERS:
        raise serializers.ValidationError(f"Send at most {MAX_HEADERS} headers.")
    seen: set[str] = set()
    for name, value in headers.items():
        _validate_header_name(name)
        if name.lower() in seen:
            raise serializers.ValidationError(f"`{name}` is set twice. Header names ignore case, so keep one.")
        seen.add(name.lower())
        _validate_header_value(name, value)


def _validate_header_name(name: str) -> None:
    if len(name) > MAX_HEADER_NAME_LENGTH or not HEADER_NAME.fullmatch(name):
        raise serializers.ValidationError(
            f"`{name}` is not a header name. Use up to {MAX_HEADER_NAME_LENGTH} visible ASCII characters, "
            "with no spaces or colons."
        )
    lowered = name.lower()
    if lowered in HEADERS_POSTHOG_SETS or lowered.startswith(HEADER_PREFIXES_POSTHOG_SETS):
        raise serializers.ValidationError(
            f"PostHog sets `{name}` itself. Use the send's own fields, such as `from`, `cc` or `subject`, instead."
        )


def _validate_header_value(name: str, value: str) -> None:
    if len(value) > MAX_HEADER_VALUE_LENGTH or not HEADER_VALUE.fullmatch(value):
        raise serializers.ValidationError(
            f"The value of `{name}` must be up to {MAX_HEADER_VALUE_LENGTH} printable ASCII characters, "
            "with no line breaks."
        )


def validate_tags(tags: list[dict[str, str]]) -> None:
    names = [tag["name"] for tag in tags]
    if len(set(names)) != len(names):
        raise serializers.ValidationError("Each tag name can appear once.")
