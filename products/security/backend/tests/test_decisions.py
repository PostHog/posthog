from datetime import timedelta

import pytest
from posthog.test.base import BaseTest

from django.utils import timezone

from products.security.backend.facade import api
from products.security.backend.facade.contracts import SubjectInput
from products.security.backend.facade.enums import Effect, Scope, Surface, TargetType
from products.security.backend.logic.decisions import decide
from products.security.backend.logic.targets import Subject
from products.security.backend.models import SecurityRule

SUBJECT = Subject.for_account(email="a@example.com")


def _rule(scope: Scope, target_type: str = TargetType.EMAIL, **kwargs) -> SecurityRule:
    return SecurityRule(
        target_type=target_type,
        target_value="a@example.com",
        effect=Effect.BLOCK,
        scope=scope,
        reason="test",
        **kwargs,
    )


class TestDecide:
    @pytest.mark.parametrize(
        "scope,blocked_surfaces",
        [
            (Scope.ALL_ACCESS, {Surface.SIGNUP, Surface.APP_ACCESS, Surface.AI_GATEWAY}),
            (Scope.SIGNUP, {Surface.SIGNUP}),
            (Scope.AI_GATEWAY, {Surface.AI_GATEWAY}),
        ],
    )
    def test_a_scope_blocks_only_its_surfaces(self, scope, blocked_surfaces):
        decisions = decide(SUBJECT, rules=[_rule(scope)])

        assert {decision.surface for decision in decisions if decision.blocked} == blocked_surfaces

    def test_a_target_type_this_code_no_longer_knows_matches_nothing(self):
        decisions = decide(SUBJECT, rules=[_rule(Scope.ALL_ACCESS, target_type="retired_type")])

        assert not any(decision.blocked for decision in decisions)


class TestDecideAgainstStoredRules(BaseTest):
    def test_only_an_active_rule_decides(self):
        now = timezone.now()
        SecurityRule.objects.create(
            target_type=TargetType.EMAIL,
            target_value="a@example.com",
            effect=Effect.BLOCK,
            scope=Scope.ALL_ACCESS,
            reason="revoked",
            revoked_at=now,
        )
        SecurityRule.objects.create(
            target_type=TargetType.EMAIL,
            target_value="a@example.com",
            effect=Effect.BLOCK,
            scope=Scope.AI_GATEWAY,
            reason="expired",
            expires_at=now - timedelta(minutes=1),
        )
        active = SecurityRule.objects.create(
            target_type=TargetType.EMAIL,
            target_value="a@example.com",
            effect=Effect.BLOCK,
            scope=Scope.SIGNUP,
            reason="active",
            expires_at=now + timedelta(days=1),
        )

        decisions = api.decide(SubjectInput(email="A@Example.com"))

        assert {(decision.surface, decision.rule_id) for decision in decisions if decision.blocked} == {
            (Surface.SIGNUP, active.id)
        }
