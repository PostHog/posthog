"""Exported enums for security."""

from enum import StrEnum


class Surface(StrEnum):
    """What a request is trying to do. A rule's scope covers one or more surfaces."""

    SIGNUP = "signup"
    APP = "app"
    AI_GATEWAY = "ai_gateway"
    EMAIL_CODE = "email_code"


class Outcome(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    # Only on EMAIL_CODE: the user skips the emailed login code.
    EXEMPT = "exempt"
