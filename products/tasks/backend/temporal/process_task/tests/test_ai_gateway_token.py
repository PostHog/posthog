import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.temporal.process_task.ai_gateway_token import (
    mint_scoped_token,
    resolve_sandbox_ai_product,
    sandbox_product_routed,
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
            ("signal_report", "research", "signals_research"),
            ("signal_report", "implementation", "signals_implementation"),
            ("signal_report", "repo_selection", "signals_repo_selection"),
            ("signal_report", "custom_agent", "signals_custom_agent"),
            ("signal_report", None, "signals"),
            ("signal_report", "match", "signals"),
            ("loop", None, "posthog_code"),
            ("slack", None, "slack_app"),
            ("support_reply", None, "conversations"),
            ("onboarding", None, "onboarding"),
            ("posthog_ai", None, "posthog_ai"),
        ],
    )
    def test_mapping(self, origin_product, ai_stage, expected):
        assert resolve_sandbox_ai_product(origin_product, ai_stage) == expected

    def test_unmapped_internal_is_background_agents(self):
        assert resolve_sandbox_ai_product("image_builder", None, internal=True) == "background_agents"

    def test_unmapped_external_is_posthog_code(self):
        assert resolve_sandbox_ai_product("user_created", None) == "posthog_code"

    def test_stage_does_not_split_non_signals_products(self):
        assert resolve_sandbox_ai_product("loop", "implementation") == "posthog_code"


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
    return settings


class TestMintScopedToken:
    def _response(self, status_code=200, body=None):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = body or {}
        response.text = ""
        return response

    def test_mints_pinned_token(self, mint_settings):
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response(200, {"token": "phe_abc"})
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

    def test_retries_mint_rate_limit_then_succeeds(self, mint_settings):
        with (
            patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post,
            patch("products.tasks.backend.temporal.process_task.ai_gateway_token.time.sleep") as sleep,
        ):
            post.side_effect = [self._response(429), self._response(200, {"token": "phe_abc"})]
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) == "phe_abc"
        assert sleep.called

    def test_gives_up_after_retries(self, mint_settings):
        with (
            patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post,
            patch("products.tasks.backend.temporal.process_task.ai_gateway_token.time.sleep"),
        ):
            post.return_value = self._response(503)
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) is None
        assert post.call_count == 3

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
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response(200, {"token": "phe_abc"})
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) == "phe_abc"
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 3 * 60 * 60 + 3600

    def test_ttl_clamps_to_gateway_max_when_run_cap_disabled(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS = 0
        mint_settings.TASKS_MAX_RUN_DURATION_SECONDS = 0
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response(200, {"token": "phe_abc"})
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) == "phe_abc"
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 86400


class TestAiGatewayEnvVars:
    def test_routed_run_gets_url_products_and_token(self, mint_settings):
        with patch(
            "products.tasks.backend.temporal.process_task.ai_gateway_token.mint_scoped_token",
            return_value="phe_abc",
        ) as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="signals_scout", ai_stage="scout:logs")
        assert env == {
            "AI_GATEWAY_URL": "https://ai-gateway.dev.posthog.dev",
            "AI_GATEWAY_PRODUCTS": "signals_scout,signals_research",
            "AI_GATEWAY_TOKEN": "phe_abc",
        }
        mint.assert_called_once_with(ai_product="signals_scout", team_id=123)

    def test_unrouted_run_gets_no_token(self, mint_settings):
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.mint_scoped_token") as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="loop")
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_mint_failure_omits_token(self, mint_settings):
        with patch(
            "products.tasks.backend.temporal.process_task.ai_gateway_token.mint_scoped_token",
            return_value=None,
        ):
            env = ai_gateway_env_vars(team_id=123, origin_product="signals_scout", ai_stage="scout")
        assert "AI_GATEWAY_TOKEN" not in env
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
