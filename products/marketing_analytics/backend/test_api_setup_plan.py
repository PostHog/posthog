from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.marketing_analytics.backend.services.setup_types import (
    Capability,
    CapabilityReadiness,
    OpenSourceWizard,
    ReadinessStatus,
    SetupPlan,
    Severity,
    Suggestion,
    SuggestionKind,
)

_PLAN_TARGET = "products.marketing_analytics.backend.api.get_setup_plan"
_FLAG_TARGET = "products.marketing_analytics.backend.api.feature_enabled_or_false"


def _plan() -> SetupPlan:
    return SetupPlan(
        suggestions=[
            Suggestion(
                id="connect_source:meta_ads",
                kind=SuggestionKind.CONNECT_SOURCE,
                severity=Severity.ERROR,
                confidence=0.95,
                title="Connect Meta Ads",
                evidence="12,480 events carry a Meta Ads utm_source but the platform isn't connected.",
                unlocks=[Capability.COST, Capability.ROAS],
                apply=OpenSourceWizard(kind="MetaAds"),
                event_volume=12480,
            )
        ],
        readiness=[
            CapabilityReadiness(
                capability=Capability.ROAS,
                status=ReadinessStatus.BLOCKED,
                explanation="Needs spend data and a conversion goal.",
                blocked_by=["connect_source:meta_ads"],
            )
        ],
        degraded=["attribution_health"],
        truncated=True,
        summary="1 suggestion(s), 1 blocking.",
    )


class TestSetupPlanEndpoint(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.pk}/marketing_analytics/setup_plan"
        cache.clear()
        flag = patch(_FLAG_TARGET, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def test_returns_the_plan(self):
        with patch(_PLAN_TARGET, return_value=_plan()):
            response = self.client.get(self.url)

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["summary"] == "1 suggestion(s), 1 blocking."
        assert [s["id"] for s in body["suggestions"]] == ["connect_source:meta_ads"]
        assert body["suggestions"][0]["unlocks"] == ["cost", "roas"]

    def test_apply_op_serializes_as_plain_json_with_its_discriminator(self):
        # The op has to survive the round trip verbatim: clients pass it straight back
        # to apply_setup_ops, and a Pydantic model leaking through would not be JSON.
        with patch(_PLAN_TARGET, return_value=_plan()):
            response = self.client.get(self.url)

        apply = response.json()["suggestions"][0]["apply"]
        assert apply == {"op": "open_source_wizard", "kind": "MetaAds"}

    def test_the_source_field_survives_shadowing_drfs_own(self):
        # `source` is DRF's attribute-mapping name on Field, so declaring one is easy to
        # get wrong — and a silently dropped key is how a client stops telling
        # deterministic suggestions from AI ones.
        with patch(_PLAN_TARGET, return_value=_plan()):
            response = self.client.get(self.url)

        assert response.json()["suggestions"][0]["source"] == "deterministic"

    def test_readiness_links_to_suggestion_ids(self):
        with patch(_PLAN_TARGET, return_value=_plan()):
            response = self.client.get(self.url)

        body = response.json()
        readiness = body["readiness"][0]
        assert readiness["blocked_by"] == ["connect_source:meta_ads"]
        assert set(readiness["blocked_by"]) <= {s["id"] for s in body["suggestions"]}

    def test_degraded_and_truncated_survive_serialization(self):
        # Both are how a client knows not to present the plan as exact or complete.
        with patch(_PLAN_TARGET, return_value=_plan()):
            response = self.client.get(self.url)

        body = response.json()
        assert body["degraded"] == ["attribution_health"]
        assert body["truncated"] is True

    def test_passes_the_date_range_through(self):
        with patch(_PLAN_TARGET, return_value=_plan()) as mock_plan:
            self.client.get(self.url, {"date_from": "-90d"})

        assert mock_plan.call_args.kwargs["date_from"] == "-90d"

    def test_defaults_the_date_range(self):
        with patch(_PLAN_TARGET, return_value=_plan()) as mock_plan:
            self.client.get(self.url)

        assert mock_plan.call_args.kwargs["date_from"] == "-30d"

    def test_service_failure_is_a_500_not_an_empty_plan(self):
        # An empty 200 would read as "nothing to fix", which is the one wrong answer.
        with patch(_PLAN_TARGET, side_effect=RuntimeError("clickhouse down")):
            response = self.client.get(self.url)

        assert response.status_code == 500
        assert "suggestions" not in response.json()

    def test_requires_authentication(self):
        self.client.logout()

        response = self.client.get(self.url)

        assert response.status_code in (401, 403)

    def test_cannot_read_another_organizations_team(self):
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other team")

        with patch(_PLAN_TARGET, return_value=_plan()):
            response = self.client.get(f"/api/projects/{other_team.pk}/marketing_analytics/setup_plan")

        assert response.status_code in (403, 404)


class TestSetupPlanFeatureFlag(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.pk}/marketing_analytics/setup_plan"
        cache.clear()

    def test_the_endpoint_is_absent_when_the_flag_is_off(self):
        with patch(_FLAG_TARGET, return_value=False), patch(_PLAN_TARGET, return_value=_plan()) as build:
            response = self.client.get(self.url)

        assert response.status_code == 404
        # 404 rather than 403 so an unreleased endpoint looks absent, not forbidden.
        assert build.call_count == 0

    def test_the_flag_is_evaluated_once_per_request(self):
        # A second call in the same request would fire a redundant `$feature_flag_called`.
        with patch(_FLAG_TARGET, return_value=True) as flag, patch(_PLAN_TARGET, return_value=_plan()):
            self.client.get(self.url)

        assert flag.call_count == 1

    def test_the_flag_is_evaluated_for_the_requesting_person(self):
        # The flag targets people, and the frontend renders the Setup tab off that same
        # per-person answer. Evaluating it against the team instead answers for nobody, so
        # the tab lands on an endpoint that 404s. Two people to also catch an answer
        # cached somewhere that outlives one request.
        other_user = User.objects.create_and_join(self.organization, "second@posthog.com", None)

        with patch(_FLAG_TARGET, return_value=True) as flag, patch(_PLAN_TARGET, return_value=_plan()):
            self.client.get(self.url)
            self.client.force_login(other_user)
            self.client.get(self.url)

        assert [call.args[1] for call in flag.call_args_list] == [self.user.distinct_id, other_user.distinct_id]
        assert flag.call_args.kwargs["groups"] == {"organization": str(self.team.organization.id)}


def _clean_plan() -> SetupPlan:
    """A complete plan — the degraded fixture above is deliberately never cached."""
    plan = _plan()
    plan.degraded = []
    plan.truncated = False
    return plan


class TestSetupPlanCaching(APIBaseTest):
    """The plan is ~6 ClickHouse queries deep, one unioning every ad adapter, so moving
    between Setup sections must not re-run it. Everything here is about not serving a
    plan that has stopped being true."""

    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.pk}/marketing_analytics/setup_plan"
        # locmem persists across tests in a process; a leaked entry would make these
        # pass or fail depending on ordering.
        cache.clear()
        # Two of these invalidate through apply_setup_ops, which requires project admin.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        flag = patch(_FLAG_TARGET, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def test_second_request_does_not_rebuild_the_plan(self):
        with patch(_PLAN_TARGET, return_value=_clean_plan()) as build:
            assert self.client.get(self.url).status_code == 200
            assert self.client.get(self.url).status_code == 200

        assert build.call_count == 1

    def test_refresh_bypasses_the_cache(self):
        with patch(_PLAN_TARGET, return_value=_clean_plan()) as build:
            self.client.get(self.url)
            self.client.get(f"{self.url}?refresh=true")

        assert build.call_count == 2

    def test_a_different_window_is_a_different_question(self):
        with patch(_PLAN_TARGET, return_value=_clean_plan()) as build:
            self.client.get(f"{self.url}?date_from=-30d")
            self.client.get(f"{self.url}?date_from=-7d")

        assert build.call_count == 2

    def test_a_degraded_plan_is_never_cached(self):
        # It's missing whole checks. Caching it would keep serving those gaps for a
        # minute after whatever caused them recovered.
        with patch(_PLAN_TARGET, return_value=_plan()) as build:
            self.client.get(self.url)
            self.client.get(self.url)

        assert build.call_count == 2

    def test_applying_ops_invalidates_the_cache(self):
        # Otherwise applying a change and reloading serves the pre-change plan, with the
        # suggestion you just fixed still sitting there — which reads as a failed apply.
        with patch(_PLAN_TARGET, return_value=_clean_plan()) as build:
            self.client.get(self.url)

            self.client.post(
                f"/api/projects/{self.team.pk}/marketing_analytics/apply_setup_ops",
                {
                    "ops": [{"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb-ads"}],
                    "source": "setup_tab",
                },
                format="json",
            )

            self.client.get(self.url)

        assert build.call_count == 2

    def test_one_users_plan_is_not_served_to_another(self):
        """The plan is built from HogQL run as the caller, and `execute_hogql_query`
        applies warehouse access control from that user — so a shared entry would serve
        the first caller's campaigns, UTM values and spend to someone whose own access
        would not return them."""
        other_user = User.objects.create_and_join(self.organization, "second@posthog.com", "password")

        with patch(_PLAN_TARGET, return_value=_clean_plan()) as build:
            self.client.get(self.url)
            self.client.force_login(other_user)
            self.client.get(self.url)

        assert build.call_count == 2

    def test_one_teams_invalidation_does_not_evict_another(self):
        other = Team.objects.create(organization=self.organization, name="second")
        other_url = f"/api/projects/{other.pk}/marketing_analytics/setup_plan"

        with patch(_PLAN_TARGET, return_value=_clean_plan()) as build:
            self.client.get(self.url)
            self.client.get(other_url)
            assert build.call_count == 2

            self.client.post(
                f"/api/projects/{self.team.pk}/marketing_analytics/apply_setup_ops",
                {
                    "ops": [{"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb-ads"}],
                    "source": "setup_tab",
                },
                format="json",
            )

            self.client.get(self.url)
            self.client.get(other_url)

        # Only this team rebuilt; the other team's entry was untouched.
        assert build.call_count == 3

    def test_one_teams_plan_is_not_served_to_another(self):
        other = Team.objects.create(organization=self.organization, name="second")

        with patch(_PLAN_TARGET, return_value=_clean_plan()) as build:
            self.client.get(self.url)
            self.client.get(f"/api/projects/{other.pk}/marketing_analytics/setup_plan")

        assert build.call_count == 2
