import uuid

import pytest

from products.security.backend.facade.enums import Effect, Scope, TargetType
from products.security.backend.logic.guards import RuleDraft, check_rule

# A public range: documentation ranges fail the global-address check by design.
PUBLIC_RANGE = "93.184.216.0/24"
ADDRESS_IN_PUBLIC_RANGE = "93.184.216.34"


def _draft(target_type: TargetType, value: str, scope: Scope = Scope.ALL_ACCESS, effect: Effect = Effect.BLOCK):
    return RuleDraft(target_type=target_type, target_value=value, effect=effect, scope=scope)


class TestCheckRule:
    @pytest.mark.parametrize(
        "draft,requester_ip,refusal",
        [
            (_draft(TargetType.EMAIL_DOMAIN, "gmail.com"), None, "free email provider"),
            (_draft(TargetType.EMAIL_DOMAIN, "mailinator.com"), None, None),
            (_draft(TargetType.EMAIL_DOMAIN, "example.com"), None, None),
            (_draft(TargetType.IP, "10.0.0.0/24"), None, "private, reserved or documentation"),
            (_draft(TargetType.IP, "203.0.113.0/24"), None, "private, reserved or documentation"),
            (_draft(TargetType.IP, "93.0.0.0/8"), None, "wider than /16"),
            (_draft(TargetType.IP, "2606:2800::/32"), None, "wider than /48"),
            (_draft(TargetType.IP, PUBLIC_RANGE), ADDRESS_IN_PUBLIC_RANGE, "lock you out"),
            # A signup block can't shut the admin out of the admin, so it may cover them.
            (_draft(TargetType.IP, PUBLIC_RANGE, scope=Scope.SIGNUP), ADDRESS_IN_PUBLIC_RANGE, None),
            (_draft(TargetType.IP, PUBLIC_RANGE), None, None),
            (_draft(TargetType.ORGANIZATION_ID, str(uuid.uuid4())), None, "can only apply to the AI gateway"),
            (_draft(TargetType.USER_UUID, str(uuid.uuid4()), scope=Scope.SIGNUP), None, "can only apply to"),
            (_draft(TargetType.EMAIL, "a@example.com", effect=Effect.EXEMPT), None, "Only block rules"),
        ],
    )
    def test_refuses_rules_that_would_misfire(self, draft, requester_ip, refusal):
        errors = check_rule(draft, requester_ip=requester_ip)

        if refusal is None:
            assert errors == []
        else:
            assert any(refusal in error for error in errors), errors
