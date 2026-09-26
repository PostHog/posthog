import uuid
from datetime import timedelta

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

import requests
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.tasks.backend.access import DesktopAccessDecision, DesktopAccessResolutionError
from products.tasks.backend.logic.services.desktop_gateway_token import DESKTOP_GATEWAY_MINTS
from products.tasks.backend.logic.services.gateway_model_pin import DESKTOP_AGENT_MODELS, FREE_TIER_MODELS

from ee.billing.billing_manager import OrganizationFundingStatus, PrepaidCreditState

_VIEW = "products.tasks.backend.presentation.views.desktop_access"
_POST = "products.tasks.backend.logic.services.desktop_gateway_token.requests.post"
_EXHAUSTED = (
    "Your team has reached its PostHog Desktop usage limit for this billing period. "
    "See https://app.posthog.com/organization/billing for your usage and limits."
)

GATEWAY_SETTINGS = {
    "DESKTOP_GATEWAY_URL": "https://ai-gateway.test/v1",
    "DESKTOP_GATEWAY_MINT_KEY": "phs_desktop",
    "DESKTOP_GATEWAY_TOKEN_CAP_USD": "200",
    "DESKTOP_GATEWAY_TOKEN_CAP_USD_OVERRIDES": "",
}


def _response(status_code: int, body: object = None) -> MagicMock:
    response = MagicMock(status_code=status_code)
    response.json.return_value = body if body is not None else {}
    return response


def _minted(token: str = "phe_new", allowed_models: list[str] | None = None) -> MagicMock:
    body: dict = {"token": token, "expires_at": "2099-01-01T00:00:00Z", "cap_usd": "200"}
    if allowed_models is not None:
        body["allowed_models"] = allowed_models
    return _response(201, body)


class _GatewayTestBase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        settings_override = override_settings(**GATEWAY_SETTINGS)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.application = OAuthApplication.objects.create(
            name="PostHog Desktop",
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            user=self.user,
        )

    def _oauth_token(self, *, scope: str = "llm_gateway:read", application=None, **fields) -> OAuthAccessToken:
        return OAuthAccessToken.objects.create(
            user=self.user,
            application=application or self.application,
            token=f"pha_desktop_{uuid.uuid4().hex}",
            expires=timezone.now() + timedelta(hours=1),
            scope=scope,
            scoped_teams=[self.team.id],
            **fields,
        )

    def _client(self, **token_fields) -> APIClient:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._oauth_token(**token_fields).token}")
        return client

    def _url(self, path: str) -> str:
        return f"/api/projects/{self.team.id}/desktop/{path}/"


class TestDesktopGatewayTokenMint(_GatewayTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.gates = {
            "rollout": patch(f"{_VIEW}.desktop_rollout_enabled", return_value=True),
            "access": patch(f"{_VIEW}.get_desktop_access_decision", return_value=DesktopAccessDecision.ALLOWED),
            "credit": patch(f"{_VIEW}.team_credit_refusal", return_value=None),
            "blocked": patch(f"{_VIEW}.wizard_identity_blocked", return_value=False),
        }
        self.mocks = {name: patcher.start() for name, patcher in self.gates.items()}
        for patcher in self.gates.values():
            self.addCleanup(patcher.stop)

    def _mint(self, client: APIClient | None = None, *, go=None, body: dict | None = None):
        with patch(_POST) as post:
            post.return_value = go if go is not None else _minted()
            response = (client or self._client()).post(self._url("gateway_token"), body or {}, format="json")
        return response, post

    def test_session_auth_is_refused(self) -> None:
        response, post = self._mint(self.client)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == {
            "enabled": False,
            "reason": "oauth_required",
            "detail": "Sign in with PostHog Desktop.",
        }
        post.assert_not_called()

    def test_personal_api_key_is_refused(self) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="k", user=self.user, secure_value=hash_key_value(key), scopes=["llm_gateway:read"]
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")
        response, post = self._mint(client)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["reason"] == "oauth_required"
        post.assert_not_called()

    def test_other_oauth_app_is_refused(self) -> None:
        other = OAuthApplication.objects.create(
            name="Other",
            client_id="other-client",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            user=self.user,
        )
        response, post = self._mint(self._client(application=other))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["reason"] == "oauth_required"
        post.assert_not_called()

    @parameterized.expand(
        [
            ("wildcard_scope", {"scope": "*"}),
            ("sandbox_scope", {"scope": "llm_gateway:read internal_run:read"}),
            ("sandbox_binding", {"sandbox_task_id": uuid.uuid4()}),
        ]
    )
    def test_non_interactive_credentials_are_refused(self, _name, fields) -> None:
        response, post = self._mint(self._client(**fields))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["reason"] == "oauth_required"
        post.assert_not_called()

    def test_impersonation_token_is_refused(self) -> None:
        staff = self._create_user("staff@posthog.com")
        response, post = self._mint(self._client(impersonated_by=staff))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["reason"] == "oauth_required"
        post.assert_not_called()

    def test_unverified_email_is_refused(self) -> None:
        with patch(f"{_VIEW}.email_verification_pending", return_value=True):
            response, post = self._mint()
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["reason"] == "email_unverified"
        post.assert_not_called()

    def test_credential_no_longer_authorized_is_refused(self) -> None:
        with patch(f"{_VIEW}.oauth_credential_authorized", return_value=False):
            response, post = self._mint()
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["reason"] == "unauthorized"
        post.assert_not_called()

    def test_blocklisted_identity_is_refused_before_the_flag(self) -> None:
        self.mocks["blocked"].return_value = True
        response, post = self._mint()
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["reason"] == "blocked"
        self.mocks["rollout"].assert_not_called()
        post.assert_not_called()
        self.mocks["blocked"].assert_called_once_with(
            distinct_id=str(self.user.distinct_id),
            email=self.user.email,
            user_uuid=str(self.user.uuid),
            organization_ids=[str(self.organization.id)],
            team_ids=[self.team.id],
            surface="desktop_gateway_token",
        )

    @override_settings(DESKTOP_GATEWAY_MINT_KEY="")
    def test_unconfigured_is_disabled(self) -> None:
        response, post = self._mint()
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"enabled": False, "reason": "unconfigured"}
        self.mocks["rollout"].assert_not_called()
        post.assert_not_called()

    def test_flag_off_is_not_rolled_out_before_access_and_billing(self) -> None:
        self.mocks["rollout"].return_value = False
        self.mocks["credit"].return_value = "posthog_code_credits_exhausted"
        response, post = self._mint()
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"enabled": False, "reason": "not_rolled_out"}
        self.mocks["access"].assert_not_called()
        self.mocks["credit"].assert_not_called()
        post.assert_not_called()

    def test_flag_is_evaluated_for_the_org_and_user(self) -> None:
        self._mint()
        organization, team, distinct_id = self.mocks["rollout"].call_args.args
        assert (organization.id, team.id, distinct_id) == (self.organization.id, self.team.id, self.user.distinct_id)

    def test_blocked_desktop_access_is_refused_before_billing(self) -> None:
        self.mocks["access"].return_value = DesktopAccessDecision.STARTUP_PLAN
        response, post = self._mint()
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == {
            "enabled": False,
            "reason": "desktop_access_blocked",
            "access": {"allowed": False, "reason": "startup_plan"},
            "detail": "PostHog Desktop isn't available for Startup or YC program organizations.",
        }
        self.mocks["credit"].assert_not_called()
        post.assert_not_called()

    def test_access_resolution_failure_is_unavailable(self) -> None:
        self.mocks["access"].side_effect = DesktopAccessResolutionError("billing down")
        response, post = self._mint()
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["reason"] == "desktop_access_unavailable"
        post.assert_not_called()

    def test_deactivated_org_answers_the_existing_429(self) -> None:
        self.mocks["credit"].return_value = "org_deactivated"
        response, post = self._mint()
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert response.json()["code"] == "organization_deactivated"
        post.assert_not_called()

    def test_deactivated_org_refuses_a_token_caller_before_the_view(self) -> None:
        self.organization.is_active = False
        self.organization.save()
        response, post = self._mint()
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["code"] == "organization_deactivated"
        post.assert_not_called()

    def test_exhausted_bucket_is_402_with_the_legacy_sentence(self) -> None:
        self.mocks["credit"].return_value = "posthog_code_credits_exhausted"
        response, post = self._mint()
        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert response.json() == {"enabled": False, "reason": "credit_bucket_exhausted", "detail": _EXHAUSTED}
        assert response["X-PostHog-Denial"] == "credit_bucket_exhausted:posthog_code_credits"
        self.mocks["credit"].assert_called_once_with(self.team.id, "posthog_code_credits")
        post.assert_not_called()

    def test_unknown_credit_state_is_disabled(self) -> None:
        self.mocks["credit"].side_effect = RuntimeError("redis down")
        with patch(f"{_VIEW}.capture_exception") as capture:
            response, post = self._mint()
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"enabled": False, "reason": "credit_state_unknown"}
        post.assert_not_called()
        capture.assert_called_once()

    def test_free_plan_mints_the_free_pin(self) -> None:
        response, post = self._mint(go=_minted(allowed_models=FREE_TIER_MODELS[:2]))
        assert response.status_code == status.HTTP_201_CREATED
        assert post.call_args.args[0] == "https://ai-gateway.test/v1/tokens"
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer phs_desktop"}
        assert post.call_args.kwargs["timeout"] == 3
        assert post.call_args.kwargs["json"] == {
            "cap_usd": "200",
            "ttl_seconds": 300,
            "product": "posthog_code",
            "obo": str(self.team.id),
            "user": self.user.distinct_id,
            "allowed_models": FREE_TIER_MODELS,
        }
        assert response.json() == {
            "enabled": True,
            "token": "phe_new",
            "expires_at": "2099-01-01T00:00:00Z",
            "cap_usd": "200",
            "gateway_url": "https://ai-gateway.test",
            "product": "posthog_code",
            "team_id": self.team.id,
            "plan": "free",
            # Go's echo, not what was sent: a region without a host shrinks the pin.
            "allowed_models": FREE_TIER_MODELS[:2],
            "product_models": DESKTOP_AGENT_MODELS,
        }

    def test_paid_plan_mints_the_desktop_pin(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.POSTHOG_CODE_USAGE, "name": "PostHog Desktop usage billing"}
        ]
        self.organization.save()
        response, post = self._mint(go=_minted(allowed_models=DESKTOP_AGENT_MODELS))
        assert response.status_code == status.HTTP_201_CREATED
        assert post.call_args.kwargs["json"]["allowed_models"] == DESKTOP_AGENT_MODELS
        assert response.json()["plan"] == "paid"
        assert response.json()["allowed_models"] == DESKTOP_AGENT_MODELS

    def test_missing_echo_falls_back_to_the_sent_pin(self) -> None:
        response, _ = self._mint()
        assert response.json()["allowed_models"] == FREE_TIER_MODELS

    def test_team_cap_override_applies(self) -> None:
        with override_settings(DESKTOP_GATEWAY_TOKEN_CAP_USD_OVERRIDES=f'{{"{self.team.id}": "350"}}'):
            _, post = self._mint()
        assert post.call_args.kwargs["json"]["cap_usd"] == "350"

    @parameterized.expand([("below_floor", 5, 60), ("above_ceiling", 999999, 86400), ("in_range", 1800, 1800)])
    def test_ttl_is_clamped(self, _name, configured, expected) -> None:
        with override_settings(DESKTOP_GATEWAY_TOKEN_TTL_SECONDS=configured):
            _, post = self._mint()
        assert post.call_args.kwargs["json"]["ttl_seconds"] == expected

    @parameterized.expand([("rate_limited", 429), ("upstream_error", 502), ("bad_request", 400)])
    def test_gateway_refusal_is_503(self, _name, go_status) -> None:
        response, _ = self._mint(go=_response(go_status, {"error": "no"}))
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"enabled": False, "reason": "mint_failed", "detail": "Gateway token mint failed."}

    @parameterized.expand(
        [
            ("rate_limited", _response(429, {"error": "no"}), "rate_limited"),
            ("upstream_error", _response(502, {"error": "no"}), "refused"),
            ("bad_request", _response(400, {"error": "no"}), "refused"),
            ("malformed", _response(201, {"token": "phe_x"}), "malformed"),
            ("ok", _minted(), "ok"),
        ]
    )
    def test_the_mint_counter_separates_the_gateway_ceiling(self, _name, go, outcome) -> None:
        def count(label: str) -> float:
            return DESKTOP_GATEWAY_MINTS.labels(outcome=label)._value.get()

        before = {label: count(label) for label in ("ok", "rate_limited", "refused", "malformed", "unreachable")}
        self._mint(go=go)
        after = {label: count(label) for label in before}
        assert {label: after[label] - before[label] for label in before} == {
            label: (1 if label == outcome else 0) for label in before
        }

    @parameterized.expand([("configured", 900, 900), ("clamped", 5, 60)])
    def test_the_mint_caches_the_funding_lookup_for_the_token_lifetime(self, _name, configured, expected) -> None:
        with override_settings(DESKTOP_GATEWAY_TOKEN_TTL_SECONDS=configured):
            self._mint()
        self.mocks["access"].assert_called_once()
        assert self.mocks["access"].call_args.kwargs == {"funding_cache_seconds": expected}

    @parameterized.expand([("valid", "350", "350", 0), ("invalid", "lots", "200", 1)])
    def test_the_default_cap_is_minted_and_only_an_invalid_one_is_reported(
        self, _name, configured, minted, reports
    ) -> None:
        from products.tasks.backend.logic.services import desktop_gateway_token

        desktop_gateway_token._valid_default_cap.cache_clear()
        with (
            override_settings(DESKTOP_GATEWAY_TOKEN_CAP_USD=configured),
            patch.object(desktop_gateway_token, "capture_exception") as capture,
        ):
            caps = [self._mint()[1].call_args.kwargs["json"]["cap_usd"] for _ in range(3)]
        assert caps == [minted] * 3
        assert capture.call_count == reports

    def test_a_gateway_429_is_not_captured_but_other_failures_are(self) -> None:
        with patch(f"{_VIEW}.capture_exception") as capture:
            limited, _ = self._mint(go=_response(429, {"error": "slow down"}))
            failed, _ = self._mint(go=_response(502, {"error": "no"}))
        assert (limited.status_code, failed.status_code) == (503, 503)
        assert limited.json()["reason"] == failed.json()["reason"] == "mint_failed"
        capture.assert_called_once()

    def test_a_bare_gateway_host_mints_and_is_returned_without_v1(self) -> None:
        with override_settings(DESKTOP_GATEWAY_URL="https://ai-gateway.us.posthog.com"):
            response, post = self._mint()
        assert response.status_code == status.HTTP_201_CREATED
        assert post.call_args.args[0] == "https://ai-gateway.us.posthog.com/v1/tokens"
        assert response.json()["gateway_url"] == "https://ai-gateway.us.posthog.com"

    def test_a_second_mint_within_the_token_lifetime_skips_the_billing_call(self) -> None:
        self.gates["access"].stop()
        with (
            patch("products.tasks.backend.access.get_feature_flag_or_none", return_value=False),
            patch(
                "products.tasks.backend.access._get_funding_status",
                return_value=OrganizationFundingStatus(
                    startup_program_label=None, prepaid_credit_state=PrepaidCreditState.NONE
                ),
            ) as funding,
        ):
            first, _ = self._mint()
            second, _ = self._mint()
        self.mocks["access"] = self.gates["access"].start()
        assert (first.status_code, second.status_code) == (status.HTTP_201_CREATED, status.HTTP_201_CREATED)
        funding.assert_called_once()

    def test_transport_failure_is_503(self) -> None:
        with patch(_POST, side_effect=requests.ReadTimeout("slow")):
            response = self._client().post(self._url("gateway_token"))
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_an_instance_id_is_ignored(self) -> None:
        for instance_id in ("laptop-1", "a:b", 7, ""):
            response, post = self._mint(body={"instance_id": instance_id})
            assert response.status_code == status.HTTP_201_CREATED
            assert "instance_id" not in post.call_args.kwargs["json"]

    def test_malformed_mint_response_is_503(self) -> None:
        response, _ = self._mint(go=_response(201, {"token": "phe_x"}))
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_per_user_throttle_refuses_after_the_hourly_ceiling(self) -> None:
        with override_settings(DESKTOP_GATEWAY_MINTS_PER_HOUR=2):
            codes = [self._mint()[0].status_code for _ in range(3)]
            third, post = self._mint()
        assert codes == [201, 201, 429]
        assert third.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert third.json() == {
            "enabled": False,
            "reason": "throttled",
            "detail": "Too many gateway token requests. Try later.",
        }
        post.assert_not_called()

    def test_the_default_ceiling_is_120_mints_an_hour(self) -> None:
        codes = [self._mint()[0].status_code for _ in range(121)]
        assert codes == [201] * 120 + [429]

    def test_a_refused_request_spends_a_slot_and_the_throttle_runs_before_the_gates(self) -> None:
        with (
            override_settings(DESKTOP_GATEWAY_MINTS_PER_HOUR=1),
            patch(f"{_VIEW}.oauth_credential_authorized", return_value=True) as authorized,
            patch(f"{_VIEW}.email_verification_pending", return_value=False) as email_pending,
        ):
            self.mocks["credit"].return_value = "posthog_code_credits_exhausted"
            refused, _ = self._mint()
            self.mocks["credit"].return_value = None
            throttled, post = self._mint()
        assert refused.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        # The throttled request reached no gate past the credential shape check.
        for gate in (email_pending, authorized, self.mocks["blocked"], self.mocks["rollout"]):
            assert gate.call_count == 1
        post.assert_not_called()

    def test_the_ceiling_resets_after_an_hour(self) -> None:
        with (
            override_settings(DESKTOP_GATEWAY_MINTS_PER_HOUR=1),
            time_machine.travel("2026-09-24T12:00:00Z", tick=False) as clock,
        ):
            first, _ = self._mint()
            clock.move_to("2026-09-24T12:59:00Z")
            within_the_hour, _ = self._mint()
            clock.move_to("2026-09-24T13:00:01Z")
            after_the_hour, _ = self._mint()
        assert [first.status_code, within_the_hour.status_code, after_the_hour.status_code] == [201, 429, 201]

    def test_the_ceiling_is_per_user(self) -> None:
        other = self._create_user("other@posthog.com")
        with override_settings(DESKTOP_GATEWAY_MINTS_PER_HOUR=1):
            first, _ = self._mint()
            other_token = OAuthAccessToken.objects.create(
                user=other,
                application=self.application,
                token=f"pha_desktop_{uuid.uuid4().hex}",
                expires=timezone.now() + timedelta(hours=1),
                scope="llm_gateway:read",
                scoped_teams=[self.team.id],
            )
            other_client = APIClient()
            other_client.credentials(HTTP_AUTHORIZATION=f"Bearer {other_token.token}")
            second, _ = self._mint(other_client)
            third, _ = self._mint()
        assert [first.status_code, second.status_code, third.status_code] == [201, 201, 429]

    def test_mint_failure_is_captured_without_code_variables(self) -> None:
        with (
            patch(f"{_VIEW}.capture_exception") as capture,
            patch(f"{_VIEW}.posthoganalytics.set_capture_exception_code_variables_context") as code_vars,
        ):
            self._mint(go=_response(500))
        code_vars.assert_called_once_with(False)
        capture.assert_called_once()


@time_machine.travel("2026-09-23T12:00:00Z", tick=False)
class TestDesktopUsageEndpoint(_GatewayTestBase):
    def _usage(self, limited_resources: dict | None = None):
        with patch(
            "ee.billing.quota_limiting.get_fresh_team_limited_resources",
            side_effect=lambda _token: {
                resource: (limited_resources or {}).get(resource.value, False)
                for resource in __import__("ee.billing.quota_limiting", fromlist=["QuotaResource"]).QuotaResource
            },
        ):
            return self._client().get(self._url("usage"))

    def test_body_matches_the_legacy_contract_field_by_field(self) -> None:
        self.organization.usage = {
            "period": ["2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"],
            "posthog_code_credits": {"usage": 1200, "todays_usage": 34, "limit": 5000},
            "posthog_code_token_credits": {"usage": 900, "todays_usage": 0},
            "sandbox_compute_credits": {"usage": 334.0},
            "sandbox_compute_cpu_millicore_seconds": {"usage": 12.5},
        }
        self.organization.available_product_features = [
            {"key": AvailableFeature.POSTHOG_CODE_USAGE, "name": "PostHog Desktop usage billing"}
        ]
        self.organization.save()

        response = self._usage()

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "product": "posthog_code",
            "user_id": self.user.id,
            "burst": {
                "used_percent": 0.0,
                "resets_in_seconds": 86400,
                "reset_at": "2026-09-24T12:00:00Z",
                "exceeded": False,
            },
            "sustained": {
                "used_percent": 0.0,
                "resets_in_seconds": 2592000,
                "reset_at": "2026-10-23T12:00:00Z",
                "exceeded": False,
            },
            "ai_credits": {
                "exhausted": False,
                "used_usd": 12.34,
                "limit_usd": 50.0,
                "breakdown": {
                    "token_credits": 900,
                    "compute_credits": 334,
                    # A fractional unit is not a count; legacy reports it as unknown.
                    "cpu_millicore_seconds": None,
                    "memory_mib_seconds": None,
                },
            },
            "is_rate_limited": False,
            "is_pro": False,
            "code_usage_subscribed": True,
            "billing_period_end": "2026-10-01T00:00:00Z",
        }

    def test_unsynced_org_reports_unknown_not_zero(self) -> None:
        body = self._usage().json()
        assert body["ai_credits"] == {"exhausted": False, "used_usd": None, "limit_usd": None, "breakdown": None}
        assert body["billing_period_end"] is None
        assert body["code_usage_subscribed"] is False

    def test_exhausted_bucket_is_rate_limited(self) -> None:
        body = self._usage({"posthog_code_credits": True}).json()
        assert body["ai_credits"]["exhausted"] is True
        assert body["is_rate_limited"] is True

    def test_ai_credits_limit_does_not_leak_into_the_desktop_bucket(self) -> None:
        body = self._usage({"ai_credits": True}).json()
        assert body["ai_credits"]["exhausted"] is False
        assert body["is_rate_limited"] is False

    def test_deactivated_org_is_exhausted_and_unbilled(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.POSTHOG_CODE_USAGE, "name": "PostHog Desktop usage billing"}
        ]
        self.organization.is_active = False
        self.organization.save()
        # Token callers are refused upstream of the view; a session reaches the body.
        with patch("ee.billing.quota_limiting.get_fresh_team_limited_resources", side_effect=Exception("unused")):
            body = self.client.get(self._url("usage")).json()
            refused = self._client().get(self._url("usage"))
        assert body["ai_credits"]["exhausted"] is True
        assert body["is_rate_limited"] is True
        assert body["code_usage_subscribed"] is False
        assert refused.status_code == status.HTTP_403_FORBIDDEN
        assert refused.json()["code"] == "organization_deactivated"


class TestDesktopEndpointsRequireAuthentication(_GatewayTestBase):
    @parameterized.expand([("mint", "post", "gateway_token"), ("usage", "get", "usage")])
    def test_anonymous_request_is_refused(self, _name, method, path) -> None:
        with patch(_POST) as post:
            response = getattr(APIClient(), method)(self._url(path), {}, format="json")
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert "enabled" not in response.json() and "ai_credits" not in response.json()
        post.assert_not_called()
