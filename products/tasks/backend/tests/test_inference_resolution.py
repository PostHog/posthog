from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration.claude_subscription import ClaudeSubscriptionStore
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.tasks.backend.facade import inference
from products.tasks.backend.logic.services.inference_resolution import (
    InvalidInferenceState,
    issue_run_claude_subscription,
    validated_inference_state,
)

MODULE = "products.tasks.backend.logic.services.inference_resolution"

FAKE_CLAUDE_TOKEN = "sk-ant-oat01-not-a-real-token-0003"
SUBSCRIPTION_CLAUDE = {"claude_model_access": "own-subscription", "claude_subscription_source": "server"}
SUBSCRIPTION_CODEX = {"codex_model_access": "own-subscription"}
CREDENTIAL_KIND = {"claude": "claude_subscription", "codex": "codex"}
STATE_UPDATES = {"claude": SUBSCRIPTION_CLAUDE, "codex": SUBSCRIPTION_CODEX}


def _connect(user: User, adapter: str, *, codex_status: str = "connected") -> None:
    if adapter == "codex":
        UserIntegration.objects.create(user=user, kind="codex", integration_id="acct", config={"status": codex_status})
        return
    ClaudeSubscriptionStore.connect(user.id, FAKE_CLAUDE_TOKEN)


class TestResolveInference(BaseTest):
    def _resolve(
        self, *, adapter: str, requested: str, stored: tuple[str, ...], flags: bool, user: User | None
    ) -> inference.InferenceDecision:
        for kind in stored:
            _connect(self.user, kind)
        with (
            patch(f"{MODULE}.claude_subscription_storage_enabled", return_value=flags),
            patch(f"{MODULE}.posthoganalytics.feature_enabled", return_value=flags),
        ):
            return inference.resolve_inference(
                user_id=user.id if user else None,
                team_id=self.team.id,
                runtime_adapter=adapter,
                requested=requested,  # type: ignore[arg-type]
            )

    @parameterized.expand(
        [
            # name, adapter, requested, stored, flags, mode
            ("auto_claude_uses_the_subscription", "claude", "auto", ("claude",), True, "own_subscription"),
            ("auto_claude_ignores_a_subscription_with_the_flag_off", "claude", "auto", ("claude",), False, "posthog"),
            ("auto_claude_with_nothing_stored", "claude", "auto", (), True, "posthog"),
            ("auto_claude_ignores_the_chatgpt_account", "claude", "auto", ("codex",), True, "posthog"),
            ("auto_codex_uses_the_chatgpt_account", "codex", "auto", ("codex",), True, "own_subscription"),
            ("auto_codex_ignores_the_account_with_the_flag_off", "codex", "auto", ("codex",), False, "posthog"),
            ("auto_codex_with_nothing_connected", "codex", "auto", (), True, "posthog"),
            ("auto_codex_ignores_the_claude_subscription", "codex", "auto", ("claude",), True, "posthog"),
            ("explicit_claude_subscription", "claude", "own_subscription", ("claude",), True, "own_subscription"),
            ("explicit_codex_subscription", "codex", "own_subscription", ("codex",), True, "own_subscription"),
            ("explicit_posthog_over_a_claude_subscription", "claude", "posthog", ("claude",), True, "posthog"),
            ("explicit_posthog_over_a_chatgpt_account", "codex", "posthog", ("codex",), True, "posthog"),
        ]
    )
    def test_resolves_the_mode_and_the_state_to_stamp(
        self, _name: str, adapter: str, requested: str, stored: tuple[str, ...], flags: bool, mode: str
    ) -> None:
        decision = self._resolve(adapter=adapter, requested=requested, stored=stored, flags=flags, user=self.user)

        own = mode == "own_subscription"
        updates = STATE_UPDATES[adapter] if own else {}
        assert decision.mode == mode
        assert decision.adapter == adapter
        assert decision.credential_kind == (CREDENTIAL_KIND[adapter] if own else None)
        assert decision.owner_user_id == (self.user.id if own else None)
        assert dict(decision.run_state_updates) == updates
        assert decision.resolved_from_auto is (requested == "auto")
        assert FAKE_CLAUDE_TOKEN not in repr(decision)
        assert inference.inference_billing_for_state({"runtime_adapter": adapter, **updates}) == mode

    def test_auto_ignores_a_chatgpt_account_that_needs_a_new_login(self) -> None:
        _connect(self.user, "codex", codex_status="reauth_required")

        decision = self._resolve(adapter="codex", requested="auto", stored=(), flags=True, user=self.user)

        assert (decision.mode, dict(decision.run_state_updates), decision.resolved_from_auto) == ("posthog", {}, True)

    @parameterized.expand(
        [
            # name, adapter, stored, flags, user, code
            ("claude_subscription_not_stored", "claude", ("codex",), True, "member", "credential_missing"),
            ("claude_subscription_flag_off", "claude", ("claude",), False, "member", "not_available"),
            ("chatgpt_account_not_connected", "codex", ("claude",), True, "member", "credential_missing"),
            ("chatgpt_flag_off", "codex", ("codex",), False, "member", "not_available"),
            ("claude_without_a_user", "claude", ("claude",), True, "none", "no_user"),
            ("codex_without_a_user", "codex", ("codex",), True, "none", "no_user"),
            ("claude_user_of_another_organization", "claude", (), True, "outsider", "no_user"),
            ("codex_user_of_another_organization", "codex", (), True, "outsider", "no_user"),
        ]
    )
    def test_an_explicit_subscription_that_cannot_be_used_is_refused(
        self, _name: str, adapter: str, stored: tuple[str, ...], flags: bool, who: str, code: str
    ) -> None:
        user: User | None = self.user if who == "member" else None
        if who == "outsider":
            user = User.objects.create_user(email="outsider@example.com", password=None, first_name="Outsider")
            _connect(user, adapter)

        with self.assertRaises(inference.InferenceUnavailable) as raised:
            self._resolve(adapter=adapter, requested="own_subscription", stored=stored, flags=flags, user=user)

        assert raised.exception.code == code
        assert raised.exception.detail
        assert FAKE_CLAUDE_TOKEN not in raised.exception.detail

    @parameterized.expand(
        [
            ("claude_no_user", "claude", False),
            ("codex_no_user", "codex", False),
            ("claude_user_of_another_organization", "claude", True),
            ("codex_user_of_another_organization", "codex", True),
        ]
    )
    def test_auto_without_a_team_member_uses_posthog(self, _name: str, adapter: str, outsider: bool) -> None:
        user = None
        if outsider:
            user = User.objects.create_user(email="outsider@example.com", password=None, first_name="Outsider")
            _connect(user, adapter)

        decision = self._resolve(adapter=adapter, requested="auto", stored=(), flags=True, user=user)

        assert (decision.mode, dict(decision.run_state_updates), decision.resolved_from_auto) == ("posthog", {}, True)


class TestIssueRunClaudeSubscription(BaseTest):
    @parameterized.expand(
        [
            ("the_stored_subscription", SUBSCRIPTION_CLAUDE, FAKE_CLAUDE_TOKEN),
            ("a_gateway_run", {}, None),
            ("a_relayed_subscription_run", {"claude_model_access": "own-subscription"}, None),
            ("a_codex_run", {**SUBSCRIPTION_CODEX, "runtime_adapter": "codex"}, None),
            ("a_run_with_two_subscriptions", {**SUBSCRIPTION_CLAUDE, **SUBSCRIPTION_CODEX}, None),
        ]
    )
    def test_a_run_gets_the_token_only_when_its_state_selects_the_stored_one(
        self, _name: str, state: dict[str, Any], expected: str | None
    ) -> None:
        _connect(self.user, "claude")
        run_state = {
            **state,
            "claude_subscription_user_id": self.user.id,
            "codex_subscription_user_id": self.user.id,
        }

        with patch(f"{MODULE}.claude_subscription_storage_enabled", return_value=True):
            grant = issue_run_claude_subscription(run_state, team_id=self.team.id)

        assert (grant.secret if grant else None) == expected
        if grant is not None:
            assert grant.secret not in repr(grant)

    def test_a_run_with_no_owner_gets_nothing(self) -> None:
        _connect(self.user, "claude")

        with patch(f"{MODULE}.claude_subscription_storage_enabled", return_value=True):
            assert issue_run_claude_subscription(SUBSCRIPTION_CLAUDE, team_id=self.team.id) is None

    @parameterized.expand(
        [
            # name, owner, the owner has a token, another team member has a token, flag
            ("owner_has_no_token", "member", False, True, True),
            ("storage_flag_off", "member", True, False, False),
            ("owner_has_no_access_to_the_team", "outsider", True, True, True),
        ]
    )
    def test_a_selected_token_that_cannot_be_used_is_missing(
        self, _name: str, owner_kind: str, owner_has_token: bool, member_has_token: bool, flag: bool
    ) -> None:
        owner = User.objects.create_and_join(self.organization, "owner@example.com", "password")
        if owner_kind == "outsider":
            owner = User.objects.create_user(email="outsider@example.com", password=None, first_name="Outsider")
        if owner_has_token:
            _connect(owner, "claude")
        if member_has_token:
            _connect(self.user, "claude")

        with (
            patch(f"{MODULE}.claude_subscription_storage_enabled", return_value=flag),
            self.assertRaises(inference.ClaudeSubscriptionMissing),
        ):
            issue_run_claude_subscription(
                {**SUBSCRIPTION_CLAUDE, "claude_subscription_user_id": owner.id}, team_id=self.team.id
            )


class TestInferenceBillingForState(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_selection", {}, "posthog"),
            ("gateway", {"claude_model_access": "posthog-gateway", "codex_model_access": "posthog-gateway"}, "posthog"),
            ("relayed_claude_subscription", {"claude_model_access": "own-subscription"}, "own_subscription"),
            ("stored_claude_subscription", SUBSCRIPTION_CLAUDE, "own_subscription"),
            ("chatgpt_subscription", {**SUBSCRIPTION_CODEX, "runtime_adapter": "codex"}, "own_subscription"),
            ("claude_api_key_access", {"claude_model_access": "own-key"}, "posthog"),
            ("codex_api_key_access", {"codex_model_access": "own-key", "runtime_adapter": "codex"}, "posthog"),
            ("unknown_access", {"claude_model_access": "free"}, "posthog"),
        ]
    )
    def test_a_run_bills_posthog_unless_it_selects_a_subscription(
        self, _name: str, state: dict[str, Any], billing: str
    ) -> None:
        assert inference.inference_billing_for_state(state) == billing


class TestValidatedInferenceState(SimpleTestCase):
    @parameterized.expand(
        [
            ("none", None, "posthog-gateway", "posthog-gateway", "relay"),
            ("posthog", {}, "posthog-gateway", "posthog-gateway", "relay"),
            ("stored_subscription", SUBSCRIPTION_CLAUDE, "own-subscription", "posthog-gateway", "server"),
            ("codex", SUBSCRIPTION_CODEX, "posthog-gateway", "own-subscription", "relay"),
        ]
    )
    def test_every_inference_key_gets_a_value(
        self, _name: str, updates: dict[str, Any] | None, claude: str, codex: str, source: str
    ) -> None:
        assert validated_inference_state(updates) == {
            "claude_model_access": claude,
            "codex_model_access": codex,
            "claude_subscription_source": source,
        }

    @parameterized.expand(
        [
            ("owner_key", {"claude_subscription_user_id": 1}),
            ("unrelated_key", {"sandbox_size": "16x64"}),
            ("unknown_access", {"claude_model_access": "free"}),
            ("claude_api_key_access", {"claude_model_access": "own-key"}),
            ("codex_api_key_access", {"codex_model_access": "own-key"}),
            ("unknown_source", {"claude_subscription_source": "desktop"}),
        ]
    )
    def test_other_keys_and_unknown_values_are_refused(self, _name: str, updates: dict[str, Any]) -> None:
        with self.assertRaises(InvalidInferenceState):
            validated_inference_state(updates)
