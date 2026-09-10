from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest

from django.urls import reverse
from django.utils import timezone

from parameterized import parameterized

from posthog.admin import register_all_admin

from products.security.backend.facade.enums import Effect, Scope, TargetType
from products.security.backend.models import SecurityRule

# Under tests `posthog/apps.py` skips the lazy admin registry, which is the only caller of
# `register_all_admin()`, so no product-local admin would be registered otherwise.
register_all_admin()


class TestSecurityRuleAdmin(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _post_add(self, **overrides: Any):
        data = {
            "target_type": TargetType.EMAIL_ROOT,
            "target_value": "Farm.Bot+7@Example.com",
            "scope": Scope.ALL_ACCESS,
            "reason": "Alias farm",
            "expires_at_0": "",
            "expires_at_1": "",
            **overrides,
        }
        return self.client.post(reverse("admin:security_securityrule_add"), data)

    def _stored_rule(self, scope: Scope = Scope.ALL_ACCESS, **kwargs: Any) -> SecurityRule:
        return SecurityRule.objects.create(
            target_type=TargetType.EMAIL_ROOT,
            target_value="farm.bot@example.com",
            effect=Effect.BLOCK,
            scope=scope,
            reason="Alias farm",
            **kwargs,
        )

    def test_first_submit_previews_without_saving(self):
        response = self._post_add()

        self.assertContains(response, "Confirm the rule")
        self.assertContains(response, "farm.bot@example.com")
        assert not SecurityRule.objects.exists()

    def test_the_add_form_offers_one_submit_that_leads_to_the_preview(self):
        response = self.client.get(reverse("admin:security_securityrule_add"))

        self.assertContains(response, 'value="Review rule"')
        self.assertNotContains(response, "Save and add another")
        self.assertNotContains(response, "Save and view")

    def test_confirmed_submit_saves_the_normalized_rule_with_its_author(self):
        response = self._post_add(_confirm_rule="1")

        assert response.status_code == 302
        rule = SecurityRule.objects.get()
        assert (rule.target_value, rule.effect, rule.created_by) == ("farm.bot@example.com", Effect.BLOCK, self.user)
        self.assertContains(self.client.get(response.url), "Block all access: Email root farm.bot@example.com")

    def test_a_saved_rule_opens_read_only(self):
        rule = self._stored_rule()

        response = self.client.get(reverse("admin:security_securityrule_change", args=[rule.id]))

        self.assertContains(response, "Email root")
        self.assertContains(response, "All access")
        self.assertContains(response, "Active")
        self.assertNotContains(response, 'name="_save"')

    def test_a_refused_rule_stays_on_the_form_with_the_reason(self):
        response = self._post_add(target_type=TargetType.EMAIL_DOMAIN, target_value="gmail.com")

        self.assertContains(response, "free email provider")
        self.assertNotContains(response, "Confirm the rule")
        assert not SecurityRule.objects.exists()

    def test_revoking_records_who_revoked(self):
        rule = self._stored_rule()

        self.client.post(
            reverse("admin:security_securityrule_changelist"),
            {"action": "revoke_selected", "_selected_action": [str(rule.id)]},
        )

        rule.refresh_from_db()
        assert rule.revoked_at is not None
        assert rule.revoked_by == self.user
        self.assertContains(self.client.get(reverse("admin:security_securityrule_history", args=[rule.id])), "Revoked")

    @parameterized.expand([("active",), ("expired",), ("revoked",)])
    def test_the_status_filter_shows_only_rules_in_that_state(self, status: str):
        now = timezone.now()
        rules = {
            "active": self._stored_rule(),
            "expired": self._stored_rule(scope=Scope.AI_GATEWAY, expires_at=now - timedelta(minutes=1)),
            "revoked": self._stored_rule(scope=Scope.SIGNUP, revoked_at=now),
        }

        response = self.client.get(reverse("admin:security_securityrule_changelist"), {"status": status})

        shown = {name for name, rule in rules.items() if f"/{rule.id}/change/" in response.content.decode()}
        assert shown == {status}

    def test_lookup_names_the_rule_that_blocks_an_alias(self):
        self._stored_rule()

        response = self.client.get(reverse("admin:security_securityrule_lookup"), {"q": "farm.bot+3@example.com"})

        self.assertContains(response, "Blocked")
        self.assertContains(response, "Email root: farm.bot@example.com")

    def test_lookup_explains_a_query_it_cannot_read(self):
        response = self.client.get(reverse("admin:security_securityrule_lookup"), {"q": "not a target"})

        self.assertContains(response, "read as any of these")
        self.assertNotContains(response, "What happens")
