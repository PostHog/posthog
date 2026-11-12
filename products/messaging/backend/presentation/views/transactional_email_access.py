from typing import Any

import posthoganalytics
from rest_framework.exceptions import NotFound
from rest_framework.throttling import BaseThrottle

from posthog.permissions import legacy_scope_object_used
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle

from products.workflows.backend.facade.transactional_emails import EMAIL_FROM_CODE_FLAG

TRANSACTIONAL_EMAIL_API_FLAG = "workflows-transactional-email-api"

# LEGACY_SCOPE_FALLBACKS lets a `hog_flow` key satisfy these scopes too.
TRANSACTIONAL_EMAIL_SEND_SCOPE = "transactional_email:write"
TRANSACTIONAL_EMAIL_STATUS_SCOPE = "transactional_email:read"


def transactional_email_authorized_by(request: Any, required_scope: str) -> str:
    return legacy_scope_object_used(request, required_scope) or "transactional_email"


def require_transactional_email_api(team: Any) -> None:
    _require_flag(team, TRANSACTIONAL_EMAIL_API_FLAG)


def require_email_from_code(team: Any) -> None:
    _require_flag(team, EMAIL_FROM_CODE_FLAG)


def require_email_status_read(team: Any) -> None:
    if not (_flag_enabled(team, TRANSACTIONAL_EMAIL_API_FLAG) or email_from_code_enabled(team)):
        raise NotFound()


def email_from_code_enabled(team: Any) -> bool:
    return _flag_enabled(team, EMAIL_FROM_CODE_FLAG)


def _require_flag(team: Any, flag: str) -> None:
    if not _flag_enabled(team, flag):
        raise NotFound()


def _flag_enabled(team: Any, flag: str) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            flag,
            str(team.uuid),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            send_feature_flag_events=False,
        )
    )


class TransactionalEmailBurstThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "transactional_email_burst"
    rate = "600/minute"


class TransactionalEmailSustainedThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "transactional_email_sustained"
    rate = "20000/hour"


class TransactionalEmailTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    """Per-team aggregate across all of a project's secret API keys."""

    scope = "transactional_email_psak_team_burst"
    rate = "600/minute"


class TransactionalEmailTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "transactional_email_psak_team_sustained"
    rate = "20000/hour"


def transactional_email_throttles() -> list[BaseThrottle]:
    # Both send routes share these scopes, so a caller can't double its rate by using both.
    return [
        TransactionalEmailBurstThrottle(),
        TransactionalEmailSustainedThrottle(),
        TransactionalEmailTeamBurstThrottle(),
        TransactionalEmailTeamSustainedThrottle(),
    ]


# Reads have their own buckets, so polling for status can't use up the send budget.
class TransactionalEmailReadBurstThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "transactional_email_read_burst"
    rate = "600/minute"


class TransactionalEmailReadSustainedThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "transactional_email_read_sustained"
    rate = "20000/hour"


class TransactionalEmailReadTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "transactional_email_read_psak_team_burst"
    rate = "600/minute"


class TransactionalEmailReadTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "transactional_email_read_psak_team_sustained"
    rate = "20000/hour"


def transactional_email_read_throttles() -> list[BaseThrottle]:
    return [
        TransactionalEmailReadBurstThrottle(),
        TransactionalEmailReadSustainedThrottle(),
        TransactionalEmailReadTeamBurstThrottle(),
        TransactionalEmailReadTeamSustainedThrottle(),
    ]
