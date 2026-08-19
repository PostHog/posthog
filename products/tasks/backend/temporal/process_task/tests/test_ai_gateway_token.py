import json
from pathlib import Path

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
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response(201, {"token": "phe_abc"})
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) == "phe_abc"
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 3 * 60 * 60 + 3600

    def test_ttl_clamps_to_gateway_max_when_run_cap_disabled(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS = 0
        mint_settings.TASKS_MAX_RUN_DURATION_SECONDS = 0
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response(201, {"token": "phe_abc"})
            assert mint_scoped_token(ai_product="signals_scout", team_id=123) == "phe_abc"
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 86400


class TestAiGatewayEnvVars:
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
        }
        mint.assert_called_once_with(ai_product="signals_scout", team_id=123, user=None)

    def test_unrouted_run_gets_no_token(self, mint_settings):
        with patch("products.tasks.backend.temporal.process_task.utils.mint_scoped_token") as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="loop")
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

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


class TestMintableGate:
    """Mint scope needs server-side provenance: `internal` and some origin_product
    values are API-settable, so a routed-but-unmintable product must never mint."""

    def test_caller_internal_flag_cannot_mint_for_background_agents(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "background_agents"
        with patch("products.tasks.backend.temporal.process_task.utils.mint_scoped_token") as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="image_builder", internal=True)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()

    def test_stageless_signal_report_cannot_mint_for_bare_signals(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_PRODUCTS = "signals"
        with patch("products.tasks.backend.temporal.process_task.utils.mint_scoped_token") as mint:
            env = ai_gateway_env_vars(team_id=123, origin_product="signal_report", ai_stage=None)
        assert "AI_GATEWAY_TOKEN" not in env
        mint.assert_not_called()


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
        )

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

    def test_malformed_overrides_fall_back_to_default(self, mint_settings):
        mint_settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES = "not json"
        with patch("products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post") as post:
            post.return_value = self._response({"token": "phe_abc"})
            mint_scoped_token(ai_product="signals_scout", team_id=2)
        assert post.call_args.kwargs["json"]["cap_usd"] == "3"
