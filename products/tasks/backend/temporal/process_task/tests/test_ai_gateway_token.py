import json
import logging
from pathlib import Path

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team

from products.signals.backend.scout_harness.suggestions import SUGGESTIONS_AI_STAGE
from products.tasks.backend import model_catalog
from products.tasks.backend.constants import RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS
from products.tasks.backend.logic.services.desktop_gateway_token import valid_caps
from products.tasks.backend.logic.services.gateway_model_pin import (
    DESKTOP_AGENT_MODELS,
    FREE_TIER_MODELS,
    FREE_TIER_PIN_KEY,
    MAX_GATEWAY_PIN_LENGTH,
    SDK_IMPLICIT_MODELS,
    pinned_run_allows_model,
)
from products.tasks.backend.logic.services.sandbox_config import MAX_SANDBOX_TTL_SECONDS
from products.tasks.backend.models import INTERACTIVE_SIGNALS_AI_STAGE_BY_ORIGIN
from products.tasks.backend.temporal.process_task import utils
from products.tasks.backend.temporal.process_task.ai_gateway_token import (
    _PRODUCT_ALLOWED_MODELS,
    AI_CREDITS_BILLED_PRODUCTS,
    INTERACTIVE_MINTABLE_PRODUCTS,
    MINTABLE_PRODUCTS,
    PRODUCT_CREDIT_BUCKET,
    SANDBOX_BOUND_MINTABLE_PRODUCTS,
    _team_credit_refusal,
    mint_refusal,
    mint_scoped_token,
    resolve_sandbox_ai_product,
    sandbox_product_routed,
    token_cap_usd,
)
from products.tasks.backend.temporal.process_task.utils import ai_gateway_env_vars


class TestResolveSandboxAiProduct:
    """Must agree with resolveAiProduct/resolveGatewayProduct in
    products/desktop/packages/agent/src/utils/gateway.ts — a disagreement makes a
    routed run mint no token (degrades to Python) or mint an unused token."""

    @pytest.mark.parametrize(
        "origin_product,ai_stage,expected",
        [
            ("signals_scout", "scout", "signals_scout"),
            ("signals_scout", "scout:web-analytics", "signals_scout"),
            ("scout_suggestions", "scout_suggestions", "signals_scout_suggestions"),
            ("signal_report", "inbox", "signals_inbox"),
            ("signals_chat", "chat", "signals_chat"),
            ("signals_chat", None, "signals"),
            ("signal_report", "research", "signals_research"),
            ("signal_report", "implementation", "signals_implementation"),
            ("signal_report", "repo_selection", "signals_repo_selection"),
            ("signal_report", "custom_agent", "signals_custom_agent"),
            ("signal_report", None, "signals"),
            ("signal_report", "match", "signals"),
            ("loop", None, "posthog_code"),
            ("slack", None, "slack_app"),
            ("workflow", None, "workflows"),
            ("support_reply", None, "conversations"),
            ("onboarding", None, "onboarding"),
            ("posthog_ai", None, "posthog_ai"),
        ],
    )
    def test_mapping(self, origin_product, ai_stage, expected):
        assert resolve_sandbox_ai_product(origin_product, ai_stage) == expected

    def test_review_hog_requires_the_server_stamped_internal_flag(self):
        assert resolve_sandbox_ai_product("review_hog", "validation-c1", internal=True) == "review_hog"
        assert resolve_sandbox_ai_product("review_hog", None, internal=True) == "review_hog"
        assert resolve_sandbox_ai_product("review_hog", "validation-c1") == "posthog_code"
        assert resolve_sandbox_ai_product("review_hog", None, internal=False) == "posthog_code"

    def test_unmapped_internal_is_background_agents(self):
        assert resolve_sandbox_ai_product("image_builder", None, internal=True) == "background_agents"

    def test_unmapped_external_is_posthog_code(self):
        assert resolve_sandbox_ai_product("user_created", None) == "posthog_code"

    def test_stage_does_not_split_non_signals_products(self):
        assert resolve_sandbox_ai_product("loop", "implementation") == "posthog_code"
        assert resolve_sandbox_ai_product("review_hog", "implementation", internal=True) == "review_hog"


class TestSharedRoutingContract:
    """Both matchers consume gateway-routing-cases.json (see the TS suite), so the
    TypeScript resolver and this Python mirror cannot drift while staying green."""

    _CASES = json.loads(
        (Path(__file__).parents[6] / "products/desktop/packages/agent/src/utils/gateway-routing-cases.json").read_text()
    )

    @pytest.mark.parametrize(
        "case", _CASES["resolve_ai_product"], ids=lambda c: f"{c['origin_product']}/{c['ai_stage']}"
    )
    def test_resolve_matches_contract(self, case):
        assert (
            resolve_sandbox_ai_product(case["origin_product"], case["ai_stage"], internal=case["internal"])
            == case["expected"]
        )

    @pytest.mark.parametrize("case", _CASES["routed"], ids=lambda c: f"{c['origin_product']}/{c['ai_stage']}")
    def test_routed_matches_contract(self, case):
        ai_product = resolve_sandbox_ai_product(case["origin_product"], case["ai_stage"], internal=case["internal"])
        assert sandbox_product_routed(ai_product, case["ai_stage"], case["allowlist"]) == case["expected"]


class TestSandboxProductRouted:
    def test_plain_entry_matches_product(self):
        assert sandbox_product_routed("signals_research", "research", "signals_research,signals_scout")

    def test_plain_entry_matches_every_scout_skill(self):
        assert sandbox_product_routed("signals_scout", "scout:logs", "signals_scout")

    def test_skill_qualified_entry_matches_only_its_skill(self):
        entries = "signals_scout:web-analytics"
        assert sandbox_product_routed("signals_scout", "scout:web-analytics", entries)
        assert not sandbox_product_routed("signals_scout", "scout:logs", entries)
        assert not sandbox_product_routed("signals_scout", "scout", entries)

    def test_unlisted_product_is_not_routed(self):
        assert not sandbox_product_routed("posthog_code", None, "signals_scout")

    def test_whitespace_and_blank_entries_tolerated(self):
        assert sandbox_product_routed("signals_custom_agent", "custom_agent", " , signals_custom_agent , ")


@pytest.fixture
def mint_settings(settings):
    settings.SANDBOX_AI_GATEWAY_URL = "https://ai-gateway.dev.posthog.dev"
    settings.SANDBOX_AI_GATEWAY_PRODUCTS = "signals_scout,signals_research"
    settings.SANDBOX_AI_GATEWAY_MINT_KEY = "phs_test_mint"
    settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD = "3"
    settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS = 14400
    settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES = ""
    settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_OVERRIDES = ""
    return settings


class TestMintScopedToken:
    def _response(self, status_code=201, body=None):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = body or {}
        response.text = ""
        return response

    def test_mints_pinned_token(self, mint_settings):
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response(201, {"token": "phe_abc"})
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) == "phe_abc"
        _, kwargs = post.call_args
        assert post.call_args[0][0] == "https://ai-gateway.dev.posthog.dev/v1/tokens"
        assert kwargs["json"] == {
            "cap_usd": "3",
            "ttl_seconds": 14400,
            "product": "signals_scout",
            "obo": "123",
        }
        assert kwargs["headers"] == {"Authorization": "Bearer phs_test_mint"}
        assert kwargs["timeout"] == 3

    def test_review_hog_mint_carries_the_model_pin(self, mint_settings):
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response(201, {"token": "phe_abc"})
            assert mint_scoped_token(ai_product="review_hog", team_id=2) == "phe_abc"
        body = post.call_args.kwargs["json"]
        assert body["product"] == "review_hog"
        assert body["allowed_models"] == _PRODUCT_ALLOWED_MODELS["review_hog"]

    @pytest.mark.parametrize("product", ["posthog_ai", "review_hog", "slack_app", "workflows"])
    def test_model_pin_follows_the_catalog(self, product):
        from products.tasks.backend.facade.run_config import RuntimeAdapter, get_models_for_runtime_adapter
        from products.tasks.backend.logic.services.gateway_model_pin import SDK_IMPLICIT_MODELS

        registry = set(get_models_for_runtime_adapter(RuntimeAdapter.CLAUDE)) | set(
            get_models_for_runtime_adapter(RuntimeAdapter.CODEX)
        )
        pin = _PRODUCT_ALLOWED_MODELS[product]
        assert len(pin) == len(set(pin))
        assert set(pin) == {model for model in registry if "/" not in model} | set(SDK_IMPLICIT_MODELS)
        assert any("/" in model for model in registry), "the catalog no longer offers a gateway-served model"

    def test_non_pinned_products_send_no_allowed_models(self, mint_settings):
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response(201, {"token": "phe_abc"})
            mint_scoped_token(ai_product="signals_scout", team_id=123)
        assert "allowed_models" not in post.call_args.kwargs["json"]

    def test_retries_mint_rate_limit_then_succeeds(self, mint_settings):
        with (
            patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post,
            patch("products.tasks.backend.temporal.process_task.ai_gateway_token.time.sleep") as sleep,
        ):
            post.side_effect = [self._response(429), self._response(201, {"token": "phe_abc"})]
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) == "phe_abc"
        assert sleep.called

    def test_accepts_200_and_201(self, mint_settings):
        """The gateway mints with 201 Created; accepting only 200 turned every
        successful mint into a silent Python-gateway fallback."""
        for code in (200, 201):
            with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
                post.return_value = self._response(code, {"token": "phe_abc"})
                assert mint_scoped_token(ai_product="signals_scout", team_id=123) == "phe_abc"

    def test_gives_up_after_retries(self, mint_settings):
        with (
            patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post,
            patch("products.tasks.backend.temporal.process_task.ai_gateway_token.time.sleep"),
        ):
            post.return_value = self._response(503)
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) is None
        assert post.call_count == 2

    def test_does_not_retry_a_credential_rejection(self, mint_settings):
        with (
            patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post,
            patch("products.tasks.backend.temporal.process_task.ai_gateway_token.time.sleep"),
        ):
            post.return_value = self._response(401)
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) is None
        assert post.call_count == 1

    def test_no_mint_key_mints_nothing(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_MINT_KEY = None
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) is None
        post.assert_not_called()

    def test_non_json_200_degrades_instead_of_raising(self, mint_settings):
        response = MagicMock()
        response.status_code = 200
        response.json.side_effect = ValueError("not json")
        response.text = "<html>proxy error</html>"
        with (
            patch(
                "products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post",
                return_value=response,
            ),
            patch("products.tasks.backend.temporal.process_task.ai_gateway_token.time.sleep"),
        ):
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) is None

    def test_ttl_derives_from_run_cap_when_unset(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS = 0
        mint_settings.TASKS_MAX_RUN_DURATION_SECONDS = 3 * 60 * 60
        mint_settings.TASKS_INTERACTIVE_SIGNALS_MAX_RUN_DURATION_SECONDS = 6 * 60 * 60
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response(201, {"token": "phe_abc"})
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) == "phe_abc"
        # A background product is hard-capped at the shorter ceiling, so the longer one must
        # not widen its token's window.
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 3 * 60 * 60 + 3600

    def test_ttl_covers_the_interactive_ceiling_for_interactive_products(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS = 0
        mint_settings.TASKS_MAX_RUN_DURATION_SECONDS = 3 * 60 * 60
        mint_settings.TASKS_INTERACTIVE_SIGNALS_MAX_RUN_DURATION_SECONDS = 6 * 60 * 60
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response(201, {"token": "phe_abc"})
            assert mint_scoped_token(ai_product="signals_inbox", team_id=123) == "phe_abc"
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 6 * 60 * 60 + 3600

    # Zero means no wall-clock ceiling, so the token must not shrink onto the background derivation.
    def test_ttl_clamps_to_gateway_max_when_the_interactive_ceiling_is_disabled(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS = 0
        mint_settings.TASKS_MAX_RUN_DURATION_SECONDS = 3 * 60 * 60
        mint_settings.TASKS_INTERACTIVE_SIGNALS_MAX_RUN_DURATION_SECONDS = 0
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response(201, {"token": "phe_abc"})
            assert mint_scoped_token(ai_product="signals_chat", team_id=123) == "phe_abc"
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 86400

    def test_ttl_clamps_to_gateway_max_when_run_cap_disabled(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS = 0
        mint_settings.TASKS_MAX_RUN_DURATION_SECONDS = 0
        mint_settings.TASKS_INTERACTIVE_SIGNALS_MAX_RUN_DURATION_SECONDS = 0
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response(201, {"token": "phe_abc"})
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) == "phe_abc"
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 86400


class TestAiGatewayEnvVars:
    @time_machine.travel("2026-09-23T12:00:00Z", tick=False)
    def test_routed_run_gets_url_products_and_token(self, mint_settings):
        with patch(
            "products.tasks.backend.temporal.process_task.utils.mint_scoped_token",
            return_value="phe_abc",
        ) as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="signals_scout", ai_stage="scout:logs")
        assert env == {
            "AI_GATEWAY_URL": "https://ai-gateway.dev.posthog.dev",
            "AI_GATEWAY_PRODUCTS": "signals_scout,signals_research",
            "AI_GATEWAY_TOKEN": "phe_abc",
            "AI_GATEWAY_TOKEN_CAP_USD": "3",
            "AI_GATEWAY_PRODUCT": "signals_scout",
            "AI_GATEWAY_AI_STAGE": "scout:logs",
        }
        mint.assert_called_once_with(ai_product="signals_scout", team_id=123, user=None)

    def test_unrouted_run_gets_no_token(self, mint_settings):
        with patch("products.tasks.backend.temporal.process_task.utils.mint_scoped_token") as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="loop")
        assert "AI_GATEWAY_TOKEN" not in env
        assert "AI_GATEWAY_PRODUCT" not in env
        assert "AI_GATEWAY_AI_STAGE" not in env
        mint.assert_not_called()

    def test_workflow_run_gets_a_pinned_token_when_routed(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "workflows"
        with (
            patch(
                "products.tasks.backend.temporal.process_task.utils.mint_scoped_token",
                return_value="phe_abc",
            ) as mint,
            patch(
                "products.tasks.backend.temporal.process_task.ai_gateway_token._team_credit_refusal",
                return_value=None,
            ),
        ):
            env = ai_gateway_env_vars(team_id=123, origin_product="workflow")
        assert env["AI_GATEWAY_TOKEN"] == "phe_abc"
        mint.assert_called_once_with(ai_product="workflows", team_id=123, user=None)

    # The agent trusts these as the worker's word, so the API must refuse a run-supplied value.
    def test_reserved_keys_cover_the_pinned_product_env(self):
        assert "AI_GATEWAY_PRODUCT" in RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS
        assert "AI_GATEWAY_AI_STAGE" in RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS
        assert "AI_GATEWAY_TOKEN_CAP_USD" in RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS

    def test_skill_qualified_allowlist_still_mints(self, mint_settings):
        """The D4-D6 batched scout flips route by skill-qualified entries alone; a mint
        gate that only honors plain product entries would silently no-op every batch."""
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "signals_scout:web-analytics"
        with patch(
            "products.tasks.backend.temporal.process_task.utils.mint_scoped_token",
            return_value="phe_abc",
        ) as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="signals_scout", ai_stage="scout:web-analytics")
        assert env["AI_GATEWAY_TOKEN"] == "phe_abc"
        mint.assert_called_once_with(ai_product="signals_scout", team_id=123, user=None)

    def test_mint_failure_omits_token(self, mint_settings):
        with patch(
            "products.tasks.backend.temporal.process_task.utils.mint_scoped_token",
            return_value=None,
        ):
            env = ai_gateway_env_vars(team_id=123, origin_product="signals_scout", ai_stage="scout")
        assert "AI_GATEWAY_TOKEN" not in env
        # No token, no pinned product: the agent must not route on a product it cannot authenticate.
        assert "AI_GATEWAY_PRODUCT" not in env
        assert env["AI_GATEWAY_URL"] == "https://ai-gateway.dev.posthog.dev"

    def test_no_run_context_still_sets_routing_pair(self, mint_settings):
        env = ai_gateway_env_vars()
        assert env == {
            "AI_GATEWAY_URL": "https://ai-gateway.dev.posthog.dev",
            "AI_GATEWAY_PRODUCTS": "signals_scout,signals_research",
        }

    def test_both_or_nothing_guard_unchanged(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_URL = None
        assert ai_gateway_env_vars(team_id=123, origin_product="signals_scout", ai_stage="scout") == {}


class TestInteractiveProductSet:
    # A third stamped stage would take the longer run ceiling and a token from the shorter one.
    def test_interactive_products_are_exactly_the_stamped_stages(self):
        assert INTERACTIVE_MINTABLE_PRODUCTS == {
            f"signals_{stage}" for stage in INTERACTIVE_SIGNALS_AI_STAGE_BY_ORIGIN.values()
        }

    def test_interactive_products_are_mintable(self):
        assert INTERACTIVE_MINTABLE_PRODUCTS <= MINTABLE_PRODUCTS


class TestMintableGate:
    """Mint scope needs server-side provenance: `internal` and some origin_product
    values are API-settable, so a routed-but-unmintable product must never mint."""

    def test_caller_internal_flag_cannot_mint_for_background_agents(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "background_agents"
        with patch("products.tasks.backend.temporal.process_task.utils.mint_scoped_token") as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="image_builder", internal=True)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_routed_review_hog_mints(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "review_hog"
        with patch(
            "products.tasks.backend.temporal.process_task.utils.mint_scoped_token",
            return_value="phe_abc",
        ) as mint:
            env = ai_gateway_env_vars(team_id=2, origin_product="review_hog", ai_stage="validation-c1", internal=True)
        assert env["AI_GATEWAY_TOKEN"] == "phe_abc"
        mint.assert_called_once_with(ai_product="review_hog", team_id=2, user=None)

    def test_non_internal_review_hog_does_not_mint(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "review_hog"
        with patch("products.tasks.backend.temporal.process_task.utils.mint_scoped_token") as mint:
            env = ai_gateway_env_vars(team_id=2, origin_product="review_hog", ai_stage="validation-c1", internal=False)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_stageless_signal_report_cannot_mint_for_bare_signals(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "signals"
        with patch("products.tasks.backend.temporal.process_task.utils.mint_scoped_token") as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="signal_report", ai_stage=None)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_stageless_chat_cannot_mint_for_bare_signals(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "signals,signals_chat"
        with patch("products.tasks.backend.temporal.process_task.utils.mint_scoped_token") as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="signals_chat", ai_stage=None)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    @pytest.mark.parametrize("origin_product,ai_stage", sorted(INTERACTIVE_SIGNALS_AI_STAGE_BY_ORIGIN.items()))
    # Reads the stage from the map create_run stamps, so a rename fails here instead of
    # resolving bare `signals`.
    def test_stamped_interactive_stages_mint_their_own_product(self, mint_settings, origin_product, ai_stage):
        expected_product = f"signals_{ai_stage}"
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = expected_product
        with patch(
            "products.tasks.backend.temporal.process_task.utils.mint_scoped_token",
            return_value="phe_abc",
        ) as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product=origin_product, ai_stage=ai_stage)
        assert env["AI_GATEWAY_PRODUCT"] == expected_product
        mint.assert_called_once_with(ai_product=expected_product, team_id=123, user=None)

    def test_suggestions_stage_mints_its_own_product(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "signals_scout_suggestions"
        with patch(
            "products.tasks.backend.temporal.process_task.utils.mint_scoped_token",
            return_value="phe_abc",
        ) as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="scout_suggestions", ai_stage=SUGGESTIONS_AI_STAGE)
        assert env["AI_GATEWAY_PRODUCT"] == "signals_scout_suggestions"
        mint.assert_called_once_with(ai_product="signals_scout_suggestions", team_id=123, user=None)


class TestProvisioningBoundaries:
    """Every provisioning path derives its gateway env through run_gateway_env_vars,
    so no path can drop the team, origin, stage, internal, or acting-identity context
    minting depends on. These pin the one derivation and each path's use of it."""

    def _ctx(self):
        ctx = MagicMock()
        ctx.team_id = 7
        ctx.origin_product = "signals_scout"
        ctx.state = {"ai_stage": "scout:logs"}
        ctx.distinct_id = "user-1"
        ctx.sandbox_environment_id = None
        ctx.model = "claude-sonnet-5"
        ctx.task_runtime = "acp"
        ctx.run_id = "run-1"
        return ctx

    def _task(self):
        task = MagicMock()
        task.internal = True
        return task

    def test_run_gateway_env_vars_maps_the_full_context(self, mint_settings):
        from products.tasks.backend.temporal.process_task import utils

        with patch.object(utils, "ai_gateway_env_vars", return_value={"AI_GATEWAY_TOKEN": "phe"}) as env:
            out = utils.run_gateway_env_vars(self._ctx(), self._task())
        assert out == {"AI_GATEWAY_TOKEN": "phe"}
        env.assert_called_once_with(
            team_id=7,
            origin_product="signals_scout",
            ai_stage="scout:logs",
            internal=True,
            distinct_id="user-1",
            state={"ai_stage": "scout:logs"},
            model="claude-sonnet-5",
            runtime="acp",
            prior_slack_run=False,
        )

    def test_non_slack_origin_skips_the_prior_run_lookup(self, mint_settings):
        from products.tasks.backend.temporal.process_task import utils

        with patch("products.tasks.backend.models.TaskRun.objects") as runs:
            utils.run_gateway_env_vars(self._ctx(), self._task())
        runs.filter.assert_not_called()

    def test_slack_run_without_its_own_stamp_looks_for_an_earlier_one(self, mint_settings):
        from products.tasks.backend.temporal.process_task import utils

        ctx = self._ctx()
        ctx.origin_product = "slack"
        ctx.state = {"run_source": "manual"}
        with patch("products.tasks.backend.models.TaskRun.objects") as runs:
            runs.filter.return_value.exists.return_value = True
            with patch.object(utils, "ai_gateway_env_vars", return_value={}) as env:
                utils.run_gateway_env_vars(ctx, self._task())
        assert env.call_args.kwargs["prior_slack_run"] is True

    def test_subscription_run_does_not_mint_gateway_credentials(self, mint_settings):
        ctx = self._ctx()
        ctx.claude_model_access = "own-subscription"
        with patch.object(utils, "mint_scoped_token") as mint:
            assert utils.run_gateway_env_vars(ctx, self._task()) == {}
        mint.assert_not_called()

    def test_snapshot_builder_uses_the_shared_derivation(self, mint_settings):
        from products.tasks.backend.temporal.process_task import utils

        ctx, task = self._ctx(), self._task()
        with (
            patch.object(utils, "run_gateway_env_vars", return_value={"AI_GATEWAY_TOKEN": "phe"}) as env,
            patch(
                "products.tasks.backend.logic.services.connection_token.get_sandbox_jwt_public_key",
                return_value="jwt",
            ),
            patch.object(utils, "get_sandbox_api_url", return_value="url"),
        ):
            out = utils.build_sandbox_environment_variables(github_token="", access_token="tok", ctx=ctx, task=task)
        env.assert_called_once_with(ctx, task)
        assert out["AI_GATEWAY_TOKEN"] == "phe"

    def test_repository_builder_uses_the_shared_derivation(self, mint_settings):
        import importlib

        mod = importlib.import_module(
            "products.tasks.backend.temporal.process_task.activities.get_sandbox_for_repository"
        )

        ctx, task = self._ctx(), self._task()
        with (
            patch.object(mod, "run_gateway_env_vars", return_value={"AI_GATEWAY_TOKEN": "phe"}) as env,
            patch.object(mod, "get_sandbox_jwt_public_key", return_value="jwt"),
            patch.object(mod, "get_sandbox_api_url", return_value="url"),
        ):
            out = mod._build_environment_variables(ctx, task, "", "tok")
        env.assert_called_once_with(ctx, task)
        assert out["AI_GATEWAY_TOKEN"] == "phe"

    def test_pinned_mint_is_stamped_on_the_run(self, mint_settings):
        env = {"AI_GATEWAY_TOKEN": "phe", "AI_GATEWAY_PRODUCT": "slack_app"}
        with (
            patch.object(utils, "ai_gateway_env_vars", return_value=env),
            patch("products.tasks.backend.models.TaskRun.update_state_atomic") as update,
        ):
            utils.run_gateway_env_vars(self._ctx(), self._task())
        update.assert_called_once_with("run-1", updates={"ai_gateway_product": "slack_app"})

    def test_unpinned_mint_is_not_stamped(self, mint_settings):
        env = {"AI_GATEWAY_TOKEN": "phe", "AI_GATEWAY_PRODUCT": "signals_scout"}
        with (
            patch.object(utils, "ai_gateway_env_vars", return_value=env),
            patch("products.tasks.backend.models.TaskRun.update_state_atomic") as update,
        ):
            utils.run_gateway_env_vars(self._ctx(), self._task())
        update.assert_not_called()

    def test_reprovision_without_a_pinned_token_clears_the_stamp(self, mint_settings):
        ctx = self._ctx()
        ctx.state = {"ai_stage": "scout:logs", "ai_gateway_product": "slack_app"}
        with (
            patch.object(utils, "ai_gateway_env_vars", return_value={}),
            patch("products.tasks.backend.models.TaskRun.update_state_atomic") as update,
        ):
            utils.run_gateway_env_vars(ctx, self._task())
        update.assert_called_once_with("run-1", remove_keys=["ai_gateway_product"])

    def test_routing_failure_leaves_the_run_on_the_python_gateway(self, mint_settings):
        with patch.object(utils, "ai_gateway_env_vars", side_effect=RuntimeError("billing is down")):
            assert utils.run_gateway_env_vars(self._ctx(), self._task()) == {}

    def test_a_pinned_token_the_stamp_could_not_record_is_dropped(self, mint_settings):
        env = {
            "AI_GATEWAY_URL": "url",
            "AI_GATEWAY_TOKEN": "phe",
            "AI_GATEWAY_TOKEN_CAP_USD": "75",
            "AI_GATEWAY_PRODUCT": "slack_app",
        }
        with (
            patch.object(utils, "ai_gateway_env_vars", return_value=env),
            patch(
                "products.tasks.backend.models.TaskRun.update_state_atomic",
                side_effect=RuntimeError("postgres is down"),
            ),
        ):
            out = utils.run_gateway_env_vars(self._ctx(), self._task())
        assert "AI_GATEWAY_TOKEN" not in out
        assert "AI_GATEWAY_TOKEN_CAP_USD" not in out
        assert out["AI_GATEWAY_URL"] == "url"

    def test_an_unpinned_token_survives_a_failed_stamp_removal(self, mint_settings):
        ctx = self._ctx()
        ctx.state = {"ai_stage": "scout:logs", "ai_gateway_product": "slack_app"}
        env = {"AI_GATEWAY_TOKEN": "phe", "AI_GATEWAY_PRODUCT": "signals_scout"}
        with (
            patch.object(utils, "ai_gateway_env_vars", return_value=env),
            patch(
                "products.tasks.backend.models.TaskRun.update_state_atomic",
                side_effect=RuntimeError("postgres is down"),
            ),
        ):
            out = utils.run_gateway_env_vars(ctx, self._task())
        assert out["AI_GATEWAY_TOKEN"] == "phe"


class TestUserPinAndCapOverride:
    def _response(self, body):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = body
        response.text = ""
        return response

    def test_mint_pins_the_acting_user(self, mint_settings):
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response({"token": "phe_abc"})
            mint_scoped_token(ai_product="signals_scout", team_id=123, user="user-distinct-1")
        assert post.call_args.kwargs["json"]["user"] == "user-distinct-1"

    def test_mint_omits_user_when_unknown(self, mint_settings):
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response({"token": "phe_abc"})
            mint_scoped_token(ai_product="signals_scout", team_id=123)
        assert "user" not in post.call_args.kwargs["json"]

    def test_cap_override_applies_per_team(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES = '{"2": "10"}'
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response({"token": "phe_abc"})
            mint_scoped_token(ai_product="signals_scout", team_id=2)
            mint_scoped_token(ai_product="signals_scout", team_id=123)
        assert post.call_args_list[0].kwargs["json"]["cap_usd"] == "10"
        assert post.call_args_list[1].kwargs["json"]["cap_usd"] == "3"

    def test_cap_product_override_beats_team_override(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES = '{"2": "10"}'
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_OVERRIDES = '{"signals_implementation": "15"}'
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response({"token": "phe_abc"})
            mint_scoped_token(ai_product="signals_implementation", team_id=2)
            mint_scoped_token(ai_product="signals_scout", team_id=2)
        assert post.call_args_list[0].kwargs["json"]["cap_usd"] == "15"
        assert post.call_args_list[1].kwargs["json"]["cap_usd"] == "10"

    @pytest.mark.parametrize("invalid_product_cap", ["", True, 0, -1, "0.0000001", "10000.000001", "NaN"])
    def test_invalid_product_cap_keeps_the_product_default(self, mint_settings, invalid_product_cap):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES = '{"2": "10"}'
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_OVERRIDES = json.dumps(
            {"signals_implementation": invalid_product_cap, "signals_scout": invalid_product_cap}
        )
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response({"token": "phe_abc"})
            mint_scoped_token(ai_product="signals_implementation", team_id=2)
            mint_scoped_token(ai_product="signals_scout", team_id=2)
        # The code default for a product that has one, else the team override.
        assert [c.kwargs["json"]["cap_usd"] for c in post.call_args_list] == ["20", "10"]

    @pytest.mark.parametrize(
        "ai_product,expected_cap",
        [
            ("signals_implementation", "20"),
            ("signals_inbox", "75"),
            ("signals_chat", "30"),
            ("slack_app", "75"),
            ("workflows", "75"),
            ("posthog_ai", "75"),
            ("posthog_code", "500"),
            ("signals_scout_suggestions", "10"),
        ],
    )
    # A cap key that stops matching the resolver's product fails here instead of quietly
    # dropping to the default. Suggestions carry no entry and take that default on purpose.
    def test_shipped_product_caps_reach_the_mint(self, settings, ai_product, expected_cap):
        settings.SANDBOX_AI_GATEWAY_URL = "https://ai-gateway.dev.posthog.dev"
        settings.SANDBOX_AI_GATEWAY_MINT_KEY = "phs_test_mint"
        settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD = "10"
        settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES = ""
        # The product overrides are left alone, to assert the value the repo ships.
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response({"token": "phe_abc"})
            mint_scoped_token(ai_product=ai_product, team_id=123)
        assert post.call_args.kwargs["json"]["cap_usd"] == expected_cap

    def test_malformed_overrides_fall_back_to_default(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES = "not json"
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response({"token": "phe_abc"})
            mint_scoped_token(ai_product="signals_scout", team_id=2)
        assert post.call_args.kwargs["json"]["cap_usd"] == "3"


class TestSlackAppMint:
    def _env(self, mint_settings, *, over_quota=False, **overrides):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "slack_app"
        kwargs: dict = {
            "team_id": 123,
            "origin_product": "slack",
            "state": {"interaction_origin": "slack"},
            "model": "claude-opus-5",
            "runtime": "acp",
            **overrides,
        }
        with (
            patch(
                "products.tasks.backend.temporal.process_task.utils.mint_scoped_token", return_value="phe_abc"
            ) as mint,
            patch(
                "products.tasks.backend.temporal.process_task.ai_gateway_token._team_credit_refusal",
                return_value=("ai_credits_exhausted" if over_quota else None),
            ),
        ):
            env = ai_gateway_env_vars(**kwargs)
        return env, mint

    def _mint_response(self):
        return MagicMock(status_code=201, json=MagicMock(return_value={"token": "phe_abc"}), text="")

    def test_stamped_slack_run_mints(self, mint_settings):
        env, mint = self._env(mint_settings)
        assert env["AI_GATEWAY_TOKEN"] == "phe_abc"
        assert env["AI_GATEWAY_PRODUCT"] == "slack_app"
        mint.assert_called_once_with(ai_product="slack_app", team_id=123, user=None)

    @pytest.mark.parametrize("state", [None, {}, {"interaction_origin": "desktop"}])
    def test_run_without_slack_provenance_does_not_mint(self, mint_settings, state):
        env, mint = self._env(mint_settings, state=state)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_pi_run_does_not_mint(self, mint_settings):
        env, mint = self._env(mint_settings, runtime="pi")
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    @pytest.mark.parametrize(
        "model", ["zai-org/glm-5.3", "@cf/zai-org/glm-5.2", "moonshotai/kimi-k3", "deepseek-ai/deepseek-v4-flash-0731"]
    )
    def test_model_outside_the_pin_does_not_mint(self, mint_settings, model):
        env, mint = self._env(mint_settings, model=model)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    @pytest.mark.parametrize("model", [None, "anthropic/claude-opus-5", "gpt-5.6-terra"])
    def test_unset_or_pinned_model_mints(self, mint_settings, model):
        env, mint = self._env(mint_settings, model=model)
        assert env["AI_GATEWAY_TOKEN"] == "phe_abc"
        mint.assert_called_once()

    def test_team_out_of_ai_credits_does_not_mint(self, mint_settings):
        env, mint = self._env(mint_settings, over_quota=True)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_credit_lookup_failure_does_not_mint(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "slack_app"
        with (
            patch("products.tasks.backend.temporal.process_task.utils.mint_scoped_token") as mint,
            patch(
                "products.tasks.backend.temporal.process_task.ai_gateway_token._team_credit_refusal",
                side_effect=RuntimeError("billing is down"),
            ),
        ):
            env = ai_gateway_env_vars(
                team_id=123,
                origin_product="slack",
                state={"interaction_origin": "slack"},
                model="claude-opus-5",
                runtime="acp",
            )
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_credit_lookup_failure_names_its_own_refusal(self):
        with patch(
            "products.tasks.backend.temporal.process_task.ai_gateway_token._team_credit_refusal",
            side_effect=RuntimeError("billing is down"),
        ):
            refusal = mint_refusal(
                "slack_app", team_id=123, state={"interaction_origin": "slack"}, model=None, runtime="acp"
            )
        assert refusal == "ai_credits_unknown"

    # The provenance gate is only as strong as PATCH protection on the key it reads.
    def test_provenance_key_is_patch_protected(self):
        from products.tasks.backend.facade.api import _PROTECTED_RUN_STATE_KEYS

        assert "interaction_origin" in _PROTECTED_RUN_STATE_KEYS

    def test_internal_slack_helper_run_mints(self, mint_settings):
        env, mint = self._env(mint_settings, state={"ai_stage": "repo_selection"}, internal=True)
        assert env["AI_GATEWAY_TOKEN"] == "phe_abc"
        assert env["AI_GATEWAY_PRODUCT"] == "slack_app"
        mint.assert_called_once()

    def test_run_after_a_stamped_run_mints(self, mint_settings):
        env, mint = self._env(mint_settings, state={"run_source": "manual"}, prior_slack_run=True)
        assert env["AI_GATEWAY_TOKEN"] == "phe_abc"
        mint.assert_called_once()

    def test_unstamped_caller_run_still_does_not_mint(self, mint_settings):
        env, mint = self._env(mint_settings, state={"run_source": "manual"})
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    @pytest.mark.parametrize("overrides", [{"runtime": "pi"}, {"model": "zai-org/glm-5.3"}])
    def test_other_gates_still_refuse_an_internal_helper_run(self, mint_settings, overrides):
        env, mint = self._env(mint_settings, state={"ai_stage": "repo_selection"}, internal=True, **overrides)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_internal_does_not_admit_a_non_slack_origin(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "slack_app,background_agents"
        env, mint = self._env(mint_settings, origin_product="user_created", state=None, internal=True)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_mint_outcomes_name_their_reason_in_the_message(self, mint_settings, caplog):
        with caplog.at_level(logging.INFO):
            self._env(mint_settings, state={"run_source": "manual"})
        skipped = [r for r in caplog.records if "mint skipped" in r.getMessage()]
        assert skipped, "no mint-skipped line was logged"
        assert "no_slack_provenance" in skipped[0].getMessage()
        assert "slack_app" in skipped[0].getMessage()

    def test_mint_failure_names_its_error_in_the_message(self, mint_settings, caplog):
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = MagicMock(status_code=429, text="mint rate limit exceeded")
            with caplog.at_level(logging.WARNING):
                assert mint_scoped_token(ai_product="slack_app", team_id=123) is None
        failed = [r for r in caplog.records if "mint failed" in r.getMessage()]
        assert failed, "no mint-failed line was logged"
        assert "HTTP 429" in failed[0].getMessage()
        assert "slack_app" in failed[0].getMessage()

    # The mocked tests never run the JSON lookup; this one does.
    @pytest.mark.django_db
    def test_earlier_slack_stamp_is_found_in_the_database(self):
        from products.tasks.backend.models import Task, TaskRun
        from products.tasks.backend.temporal.process_task.utils import _task_has_stamped_slack_run

        organization = Organization.objects.create(name="Slack Org")
        team = Team.objects.create(organization=organization, name="Slack Team")
        task = Task.objects.create(
            team=team, title="From Slack", description="thread", origin_product=Task.OriginProduct.SLACK
        )
        unstamped = {"run_source": "manual"}
        assert _task_has_stamped_slack_run(task, "slack", unstamped) is False

        # The run being provisioned is already a row, so matching any run would vouch for every Slack run.
        TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.QUEUED, state=unstamped)
        assert _task_has_stamped_slack_run(task, "slack", unstamped) is False

        TaskRun.objects.create(
            task=task, team=team, status=TaskRun.Status.COMPLETED, state={"interaction_origin": "slack"}
        )
        assert _task_has_stamped_slack_run(task, "slack", unstamped) is True
        other = Task.objects.create(
            team=team, title="Other", description="other", origin_product=Task.OriginProduct.SLACK
        )
        assert _task_has_stamped_slack_run(other, "slack", unstamped) is False

    @pytest.mark.django_db
    def test_quota_check_reads_the_team_token_and_bucket(self):
        from ee.billing.quota_limiting import QuotaResource

        organization = Organization.objects.create(name="Quota Org")
        team = Team.objects.create(organization=organization, name="Quota Team")
        with patch("ee.billing.quota_limiting.is_team_over_credit_budget", return_value=True) as quota:
            assert _team_credit_refusal(team.id, "ai_credits") == "ai_credits_exhausted"
            assert _team_credit_refusal(team.id + 10_000, "ai_credits") is None
        quota.assert_called_once_with(team.api_token, QuotaResource.AI_CREDITS)
        with patch("ee.billing.quota_limiting.is_team_over_credit_budget", return_value=False) as quota:
            assert _team_credit_refusal(team.id, "posthog_code_credits") is None
        quota.assert_called_once_with(team.api_token, QuotaResource.POSTHOG_CODE_CREDITS)

    @pytest.mark.django_db
    def test_deactivated_org_refuses_before_the_bucket_is_read(self):
        organization = Organization.objects.create(name="Gone Org", is_active=False)
        team = Team.objects.create(organization=organization, name="Gone Team")
        with patch("ee.billing.quota_limiting.is_team_over_credit_budget") as quota:
            assert _team_credit_refusal(team.id, "ai_credits") == "org_deactivated"
        quota.assert_not_called()

    def test_mint_carries_the_first_party_pin(self, mint_settings):
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._mint_response()
            assert mint_scoped_token(ai_product="slack_app", team_id=2) == "phe_abc"
        body = post.call_args.kwargs["json"]
        assert body["product"] == "slack_app"
        assert body["allowed_models"] == _PRODUCT_ALLOWED_MODELS["slack_app"]

    def test_pin_covers_every_first_party_catalog_model(self):
        first_party = {entry.id for entry in model_catalog.MODELS if "/" not in entry.id}
        missing = first_party - set(_PRODUCT_ALLOWED_MODELS["slack_app"])
        assert not missing, f"catalog models absent from the slack_app pin: {sorted(missing)}"

    def test_ttl_covers_the_sandbox_lifetime(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS = 0
        mint_settings.TASKS_MAX_RUN_DURATION_SECONDS = 3 * 60 * 60
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._mint_response()
            mint_scoped_token(ai_product="slack_app", team_id=2)
        assert post.call_args.kwargs["json"]["ttl_seconds"] == MAX_SANDBOX_TTL_SECONDS + 3600


_CREDIT_LOOKUP = "products.tasks.backend.temporal.process_task.ai_gateway_token._team_credit_refusal"
_POSTHOG_CODE_GATE = "products.tasks.backend.temporal.process_task.ai_gateway_token._posthog_code_refusal"
_ROLLOUT = "products.tasks.backend.temporal.process_task.ai_gateway_token.desktop_rollout_enabled"


class TestMintRefusalScope:
    def test_ai_credits_billed_products(self):
        assert AI_CREDITS_BILLED_PRODUCTS == {"posthog_ai", "slack_app", "workflows"}
        assert AI_CREDITS_BILLED_PRODUCTS <= MINTABLE_PRODUCTS

    def test_product_credit_buckets_are_quota_resources(self):
        from ee.billing.quota_limiting import QuotaResource

        assert PRODUCT_CREDIT_BUCKET == {
            "posthog_ai": "ai_credits",
            "posthog_code": "posthog_code_credits",
            "slack_app": "ai_credits",
            "workflows": "ai_credits",
        }
        assert set(PRODUCT_CREDIT_BUCKET.values()) == {
            QuotaResource.AI_CREDITS.value,
            QuotaResource.POSTHOG_CODE_CREDITS.value,
        }

    def test_posthog_code_refuses_on_its_own_bucket(self):
        with (
            patch(_POSTHOG_CODE_GATE, return_value=None),
            patch(_CREDIT_LOOKUP, return_value="posthog_code_credits_exhausted") as quota,
        ):
            refusal = mint_refusal("posthog_code", team_id=2, state=None, model=None, runtime="acp")
        assert refusal == "posthog_code_credits_exhausted"
        quota.assert_called_once_with(2, "posthog_code_credits")

    def test_lookup_failure_names_the_bucket(self):
        with patch(_POSTHOG_CODE_GATE, return_value=None), patch(_CREDIT_LOOKUP, side_effect=RuntimeError("down")):
            refusal = mint_refusal("posthog_code", team_id=2, state=None, model=None, runtime="acp")
        assert refusal == "posthog_code_credits_unknown"

    def test_deactivated_org_does_not_mint(self):
        with patch(_CREDIT_LOOKUP, return_value="org_deactivated"):
            assert mint_refusal("workflows", team_id=2, state=None, model=None, runtime="acp") == "org_deactivated"

    @pytest.mark.parametrize("product", ["workflows", "review_hog", "signals_scout"])
    def test_slack_provenance_gate_leaves_other_products_alone(self, product):
        with patch(_CREDIT_LOOKUP, return_value=None):
            assert mint_refusal(product, team_id=2, state=None, model=None, runtime="acp") is None

    @pytest.mark.parametrize("product", ["workflows", "review_hog", "signals_scout"])
    def test_pi_runs_never_mint(self, product):
        assert mint_refusal(product, team_id=2, state=None, model=None, runtime="pi") == "pi_runtime"

    @pytest.mark.parametrize("product", ["posthog_ai", "workflows", "review_hog"])
    def test_pinned_products_refuse_an_off_pin_model(self, product):
        refusal = mint_refusal(product, team_id=2, state=None, model="zai-org/glm-5.3", runtime="acp")
        assert refusal == "model_outside_pin"

    def test_unpinned_products_take_any_model(self):
        assert mint_refusal("signals_scout", team_id=2, state=None, model="zai-org/glm-5.3", runtime="acp") is None

    @pytest.mark.parametrize("product", ["review_hog", "signals_scout", "signals_implementation"])
    def test_products_billed_elsewhere_skip_the_credit_check(self, product):
        with patch(_CREDIT_LOOKUP, return_value="ai_credits_exhausted") as quota:
            assert mint_refusal(product, team_id=2, state=None, model=None, runtime="acp") is None
        quota.assert_not_called()


class TestWorkflowsMint:
    def _env(self, mint_settings, *, over_quota=False, **overrides):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "workflows"
        kwargs: dict = {
            "team_id": 123,
            "origin_product": "workflow",
            "state": None,
            "model": "claude-opus-5",
            "runtime": "acp",
            **overrides,
        }
        with (
            patch(
                "products.tasks.backend.temporal.process_task.utils.mint_scoped_token", return_value="phe_abc"
            ) as mint,
            patch(_CREDIT_LOOKUP, return_value=("ai_credits_exhausted" if over_quota else None)),
        ):
            env = ai_gateway_env_vars(**kwargs)
        return env, mint

    def test_workflow_run_mints_a_workflows_token(self, mint_settings):
        env, mint = self._env(mint_settings)
        assert env["AI_GATEWAY_TOKEN"] == "phe_abc"
        assert env["AI_GATEWAY_PRODUCT"] == "workflows"
        mint.assert_called_once_with(ai_product="workflows", team_id=123, user=None)

    def test_pi_run_does_not_mint(self, mint_settings):
        env, mint = self._env(mint_settings, runtime="pi")
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    @pytest.mark.parametrize("model", ["zai-org/glm-5.3", "moonshotai/kimi-k3"])
    def test_model_outside_the_pin_does_not_mint(self, mint_settings, model):
        env, mint = self._env(mint_settings, model=model)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_team_out_of_ai_credits_does_not_mint(self, mint_settings):
        env, mint = self._env(mint_settings, over_quota=True)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_credit_lookup_failure_does_not_mint(self, mint_settings):
        with patch(_CREDIT_LOOKUP, side_effect=RuntimeError("billing is down")):
            refusal = mint_refusal("workflows", team_id=123, state=None, model="claude-opus-5", runtime="acp")
        assert refusal == "ai_credits_unknown"

    def test_mint_carries_the_first_party_pin(self, mint_settings):
        response = MagicMock(status_code=201, json=MagicMock(return_value={"token": "phe_abc"}), text="")
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = response
            assert mint_scoped_token(ai_product="workflows", team_id=2) == "phe_abc"
        body = post.call_args.kwargs["json"]
        assert body["product"] == "workflows"
        assert body["allowed_models"] == _PRODUCT_ALLOWED_MODELS["workflows"]

    def test_ttl_covers_the_background_run_cap(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS = 0
        mint_settings.TASKS_MAX_RUN_DURATION_SECONDS = 3 * 60 * 60
        response = MagicMock(status_code=201, json=MagicMock(return_value={"token": "phe_abc"}), text="")
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = response
            mint_scoped_token(ai_product="workflows", team_id=2)
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 4 * 60 * 60


class TestPosthogAiMint:
    def _env(self, mint_settings, *, over_quota=False, **overrides):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "posthog_ai"
        kwargs: dict = {
            "team_id": 123,
            "origin_product": "posthog_ai",
            "state": None,
            "model": "claude-opus-4-8",
            "runtime": "acp",
            **overrides,
        }
        with (
            patch(
                "products.tasks.backend.temporal.process_task.utils.mint_scoped_token", return_value="phe_abc"
            ) as mint,
            patch(_CREDIT_LOOKUP, return_value="ai_credits_exhausted" if over_quota else None),
        ):
            env = ai_gateway_env_vars(**kwargs)
        return env, mint

    def test_posthog_ai_run_mints_a_posthog_ai_token(self, mint_settings):
        env, mint = self._env(mint_settings)
        assert env["AI_GATEWAY_TOKEN"] == "phe_abc"
        assert env["AI_GATEWAY_PRODUCT"] == "posthog_ai"
        mint.assert_called_once_with(ai_product="posthog_ai", team_id=123, user=None)

    def test_unrouted_posthog_ai_run_does_not_mint(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "workflows"
        with patch("products.tasks.backend.temporal.process_task.utils.mint_scoped_token") as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="posthog_ai", model="claude-opus-4-8", runtime="acp")
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    @pytest.mark.parametrize("model", ["zai-org/glm-5.3", "moonshotai/kimi-k3"])
    def test_model_outside_the_pin_does_not_mint(self, mint_settings, model):
        env, mint = self._env(mint_settings, model=model)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_team_out_of_ai_credits_does_not_mint(self, mint_settings):
        env, mint = self._env(mint_settings, over_quota=True)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_mint_carries_the_first_party_pin(self, mint_settings):
        response = MagicMock(status_code=201, json=MagicMock(return_value={"token": "phe_abc"}), text="")
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = response
            assert mint_scoped_token(ai_product="posthog_ai", team_id=2) == "phe_abc"
        body = post.call_args.kwargs["json"]
        assert body["product"] == "posthog_ai"
        assert body["allowed_models"] == _PRODUCT_ALLOWED_MODELS["posthog_ai"]

    def test_ttl_covers_the_sandbox_lifetime(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS = 0
        mint_settings.TASKS_MAX_RUN_DURATION_SECONDS = 3 * 60 * 60
        response = MagicMock(status_code=201, json=MagicMock(return_value={"token": "phe_abc"}), text="")
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = response
            mint_scoped_token(ai_product="posthog_ai", team_id=2)
        assert post.call_args.kwargs["json"]["ttl_seconds"] == MAX_SANDBOX_TTL_SECONDS + 3600


class TestPosthogCodeSandboxMint:
    def _team(self, *, paid: bool) -> Team:
        organization = Organization.objects.create(name="Code Org")
        if paid:
            organization.available_product_features = [
                {"key": AvailableFeature.POSTHOG_CODE_USAGE, "name": "PostHog Desktop usage billing"}
            ]
            organization.save()
        return Team.objects.create(organization=organization, name="Code Team")

    def _mint_response(self, token="phe_abc", expires_at="2026-09-24T12:00:00Z"):
        return MagicMock(status_code=201, json=MagicMock(return_value={"token": token, "expires_at": expires_at}))

    def test_posthog_code_is_mintable_and_sandbox_bound(self):
        assert "posthog_code" in MINTABLE_PRODUCTS
        assert "posthog_code" in SANDBOX_BOUND_MINTABLE_PRODUCTS

    def test_pin_holds_every_catalog_id_and_fits_the_gateway(self):
        pin = _PRODUCT_ALLOWED_MODELS["posthog_code"]
        assert pin == DESKTOP_AGENT_MODELS
        assert len(pin) == len(set(pin)) <= MAX_GATEWAY_PIN_LENGTH
        assert {entry.id for entry in model_catalog.MODELS} <= set(pin)
        assert set(SDK_IMPLICIT_MODELS) <= set(pin)
        assert {"gpt-5.4", "gpt-5.3-codex", "gpt-5.2", "gpt-5-mini"} <= set(pin)
        assert any("/" in model for model in pin)

    def test_free_pin_is_the_three_open_weight_models(self):
        assert FREE_TIER_MODELS == ["@cf/zai-org/glm-5.2", "deepseek-ai/deepseek-v4-flash-0731", "moonshotai/kimi-k3"]
        assert _PRODUCT_ALLOWED_MODELS[FREE_TIER_PIN_KEY] == FREE_TIER_MODELS

    def test_ttl_is_the_sandbox_lifetime_plus_an_hour(self, mint_settings):
        # The sandbox dies at its TTL and a new one mints its own token, so a leaked token
        # outlives its sandbox by the settle hour at most.
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS = 0
        mint_settings.TASKS_MAX_RUN_DURATION_SECONDS = 3 * 60 * 60
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._mint_response()
            mint_scoped_token(ai_product="posthog_code", team_id=2)
        assert post.call_args.kwargs["json"]["ttl_seconds"] == MAX_SANDBOX_TTL_SECONDS + 3600

    def test_env_product_caps_merge_onto_the_defaults(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_OVERRIDES = '{"posthog_ai": "90", "review_hog": "75"}'
        caps = {product: token_cap_usd(2, product) for product in ("posthog_ai", "review_hog", "posthog_code")}
        assert caps == {"posthog_ai": "90", "review_hog": "75", "posthog_code": "500"}

    @pytest.mark.parametrize(
        "raw",
        ["{'posthog_code': '5'}", '["posthog_code"]', '{"posthog_code": "5", "posthog_ai": "not a number"}'],
    )
    def test_bad_product_caps_keep_the_defaults_and_are_captured_once(self, mint_settings, raw):
        valid_caps.cache_clear()
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_OVERRIDES = raw
        with patch("products.tasks.backend.logic.services.desktop_gateway_token.capture_exception") as capture:
            caps = [token_cap_usd(2, "posthog_ai") for _ in range(3)]
        assert caps == ["75"] * 3
        capture.assert_called_once()

    def test_a_valid_entry_survives_an_invalid_sibling(self, mint_settings):
        valid_caps.cache_clear()
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_OVERRIDES = (
            '{"posthog_code": "450", "posthog_ai": "bad"}'
        )
        with patch("products.tasks.backend.logic.services.desktop_gateway_token.capture_exception"):
            assert token_cap_usd(2, "posthog_code") == "450"
            assert token_cap_usd(2, "posthog_ai") == "75"

    def test_a_bad_cap_map_is_reported_without_code_variables(self, mint_settings):
        valid_caps.cache_clear()
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_OVERRIDES = "not json"
        module = "products.tasks.backend.logic.services.desktop_gateway_token"
        with (
            patch(f"{module}.capture_exception"),
            patch(f"{module}.posthoganalytics.set_capture_exception_code_variables_context") as code_variables,
        ):
            token_cap_usd(2, "posthog_ai")
        code_variables.assert_called_once_with(False)

    def test_product_cap_beats_the_team_override(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES = '{"2": "10"}'
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_OVERRIDES = '{"posthog_code": "500"}'
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._mint_response()
            mint_scoped_token(ai_product="posthog_code", team_id=2)
        assert post.call_args.kwargs["json"]["cap_usd"] == "500"

    def test_paid_mint_sends_the_desktop_pin_and_an_explicit_pin_replaces_it(self, mint_settings):
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._mint_response()
            mint_scoped_token(ai_product="posthog_code", team_id=2)
            mint_scoped_token(ai_product="posthog_code", team_id=2, allowed_models=FREE_TIER_MODELS)
        assert post.call_args_list[0].kwargs["json"]["allowed_models"] == DESKTOP_AGENT_MODELS
        assert post.call_args_list[1].kwargs["json"]["allowed_models"] == FREE_TIER_MODELS

    @pytest.mark.django_db
    def test_flag_off_skips_as_not_rolled_out(self, mint_settings):
        team = self._team(paid=True)
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "posthog_code"
        with (
            patch(_ROLLOUT, return_value=False),
            patch("products.tasks.backend.temporal.process_task.utils.mint_scoped_token") as mint,
            patch.object(utils, "logger") as log,
        ):
            env = ai_gateway_env_vars(team_id=team.id, origin_product="user_created", model="claude-opus-5")
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()
        assert log.info.call_args.kwargs["extra"]["reason"] == "not_rolled_out"

    @pytest.mark.django_db
    def test_flag_outage_reads_as_off(self):
        team = self._team(paid=True)
        with patch(
            "products.tasks.backend.logic.services.desktop_gateway_token.feature_enabled_or_false",
            side_effect=RuntimeError("flags down"),
        ):
            assert mint_refusal("posthog_code", team_id=team.id, state=None, model=None, runtime="acp") == (
                "not_rolled_out"
            )

    @pytest.mark.django_db
    def test_flag_is_evaluated_for_the_team_org(self):
        team = self._team(paid=True)
        with (
            patch(
                "products.tasks.backend.logic.services.desktop_gateway_token.feature_enabled_or_false",
                return_value=True,
            ) as flag,
            patch(_CREDIT_LOOKUP, return_value=None),
        ):
            assert mint_refusal("posthog_code", team_id=team.id, state=None, model=None, runtime="acp") is None
        assert flag.call_args.args[0] == "posthog-desktop-ai-gateway"
        assert flag.call_args.kwargs["groups"]["organization"] == str(team.organization_id)

    @pytest.mark.django_db
    def test_off_pin_model_refuses(self):
        team = self._team(paid=True)
        with patch(_ROLLOUT, return_value=True), patch(_CREDIT_LOOKUP, return_value=None):
            refusal = mint_refusal("posthog_code", team_id=team.id, state=None, model="gpt-5.5-codex", runtime="acp")
        assert refusal == "model_outside_pin"

    @pytest.mark.django_db
    @pytest.mark.parametrize("model", [None, "claude-opus-5", "zai-org/glm-5.3"])
    def test_free_plan_refuses_a_model_outside_the_free_pin(self, model):
        team = self._team(paid=False)
        with patch(_ROLLOUT, return_value=True), patch(_CREDIT_LOOKUP, return_value=None):
            refusal = mint_refusal("posthog_code", team_id=team.id, state=None, model=model, runtime="acp")
        assert refusal == "model_outside_pin"

    @pytest.mark.django_db
    def test_free_plan_mints_the_free_pin_and_stamps_it(self, mint_settings):
        team = self._team(paid=False)
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "posthog_code"
        with (
            patch(_ROLLOUT, return_value=True),
            patch(_CREDIT_LOOKUP, return_value=None),
            patch(
                "products.tasks.backend.temporal.process_task.utils.mint_scoped_token", return_value="phe_abc"
            ) as mint,
        ):
            env = ai_gateway_env_vars(team_id=team.id, origin_product="user_created", model="@cf/zai-org/glm-5.2")
        mint.assert_called_once_with(
            ai_product="posthog_code", team_id=team.id, user=None, allowed_models=FREE_TIER_MODELS
        )
        assert env["AI_GATEWAY_PRODUCT"] == "posthog_code"
        assert env[utils._PIN_KEY_ENV] == FREE_TIER_PIN_KEY

    @pytest.mark.django_db
    def test_paid_plan_mints_the_product_pin(self, mint_settings):
        team = self._team(paid=True)
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "posthog_code"
        with (
            patch(_ROLLOUT, return_value=True),
            patch(_CREDIT_LOOKUP, return_value=None),
            patch(
                "products.tasks.backend.temporal.process_task.utils.mint_scoped_token", return_value="phe_abc"
            ) as mint,
        ):
            env = ai_gateway_env_vars(team_id=team.id, origin_product="loop", model="claude-opus-5")
        mint.assert_called_once_with(ai_product="posthog_code", team_id=team.id, user=None)
        assert env["AI_GATEWAY_TOKEN"] == "phe_abc"
        assert utils._PIN_KEY_ENV not in env

    def test_run_state_stamps_the_product_pin(self, mint_settings):
        env = {"AI_GATEWAY_TOKEN": "phe", "AI_GATEWAY_PRODUCT": "posthog_code"}
        with (
            patch.object(utils, "ai_gateway_env_vars", return_value=env),
            patch("products.tasks.backend.models.TaskRun.update_state_atomic") as update,
        ):
            utils.run_gateway_env_vars(TestProvisioningBoundaries()._ctx(), TestProvisioningBoundaries()._task())
        update.assert_called_once_with("run-1", updates={"ai_gateway_product": "posthog_code"})

    def test_free_run_stamps_the_free_pin_and_hides_the_marker(self, mint_settings):
        env = {"AI_GATEWAY_TOKEN": "phe", "AI_GATEWAY_PRODUCT": "posthog_code", utils._PIN_KEY_ENV: FREE_TIER_PIN_KEY}
        with (
            patch.object(utils, "ai_gateway_env_vars", return_value=env),
            patch("products.tasks.backend.models.TaskRun.update_state_atomic") as update,
        ):
            out = utils.run_gateway_env_vars(TestProvisioningBoundaries()._ctx(), TestProvisioningBoundaries()._task())
        update.assert_called_once_with("run-1", updates={"ai_gateway_product": FREE_TIER_PIN_KEY})
        assert utils._PIN_KEY_ENV not in out
        assert out["AI_GATEWAY_TOKEN"] == "phe"

    def test_free_stamp_blocks_a_switch_to_a_paid_model(self):
        state = {"ai_gateway_product": FREE_TIER_PIN_KEY}
        assert pinned_run_allows_model(state, "moonshotai/kimi-k3")
        assert not pinned_run_allows_model(state, "claude-opus-5")
        assert pinned_run_allows_model({"ai_gateway_product": "posthog_code"}, "claude-opus-5")
