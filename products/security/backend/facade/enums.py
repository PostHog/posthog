"""Exported enums for security."""

from enum import StrEnum


class Surface(StrEnum):
    """What a request is trying to do. A rule's scope covers one or more surfaces."""

    SIGNUP = "signup"
    APP = "app"
    AI_GATEWAY = "ai_gateway"
    EMAIL_CODE = "email_code"
    SIGNUP_RISK = "signup_risk"


class Outcome(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    # On EMAIL_CODE the user skips the emailed login code. On SIGNUP_RISK the
    # signup skips the WorkOS Radar verdict.
    EXEMPT = "exempt"
