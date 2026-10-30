from typing import cast
from uuid import UUID

import structlog
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request

from posthog.llm.wizard_blocklist import WIZARD_BLOCKED_DETAIL
from posthog.models import User
from posthog.utils import get_trusted_client_ip

from products.security.backend.facade.api import access_refused as security_access_refused
from products.security.backend.facade.contracts import SubjectInput as SecuritySubject
from products.security.backend.facade.enums import Surface as SecuritySurface

logger = structlog.get_logger(__name__)


def refuse_blocked_gateway_identity(request: Request, organization_id: UUID, *, call_site: str) -> None:
    """Refuse a cloud run to an identity an enforced AI gateway rule blocks.

    The run mints its gateway token later, in a workflow with no request, so this is the only
    point where a rule on the caller's IP can match.
    """
    user = cast(User, request.user)
    try:
        refused = security_access_refused(
            SecuritySubject(
                email=user.email,
                user_uuid=str(user.uuid),
                organization_ids=(str(organization_id),),
                ip=get_trusted_client_ip(getattr(request, "_request", request)),
            ),
            SecuritySurface.AI_GATEWAY,
            call_site=call_site,
        )
    except Exception:
        logger.exception("security_access_check_site_failed", call_site=call_site)
        refused = False
    if refused:
        raise PermissionDenied(WIZARD_BLOCKED_DETAIL)
