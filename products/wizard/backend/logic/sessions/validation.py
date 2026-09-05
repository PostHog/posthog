import re

_SAFE_CHANNEL_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.\-]{1,255}$")


def validate_channel_identifier(value: str, name: str) -> None:
    if _SAFE_CHANNEL_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} must match {_SAFE_CHANNEL_IDENTIFIER.pattern}; got {value!r}")
