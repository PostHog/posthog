"""Exported enums for security."""

from enum import StrEnum


class TargetType(StrEnum):
    USER_UUID = "user_uuid"
    EMAIL = "email"
    EMAIL_ROOT = "email_root"
    EMAIL_DOMAIN = "email_domain"
    ORGANIZATION_ID = "organization_id"
    TEAM_ID = "team_id"
    IP = "ip"


class Effect(StrEnum):
    BLOCK = "block"
    EXEMPT = "exempt"
    LIMIT = "limit"


class Scope(StrEnum):
    ALL_ACCESS = "all_access"
    SIGNUP = "signup"
    AI_GATEWAY = "ai_gateway"


class Surface(StrEnum):
    """What a request is trying to do. A rule's scope maps onto one or more surfaces."""

    SIGNUP = "signup"
    APP_ACCESS = "app_access"
    AI_GATEWAY = "ai_gateway"
