from datetime import timedelta
from types import SimpleNamespace

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from anthropic.types import ToolUseBlock
from parameterized import parameterized

from posthog.auth import MCP_USER_AGENT_MARKER
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tag_value
from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.organization import OrganizationMembership
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team_marketing_analytics_config import TeamMarketingAnalyticsConfig

from products.event_definitions.backend.models.event_property import EventProperty
from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.marketing_analytics.backend.api import ConversionGoalPreviewSerializer
from products.marketing_analytics.backend.models.conversion_setup import (
    ConversionGoalPreviewEvidence,
    ConversionRecommendationRun,
)
from products.marketing_analytics.backend.services.conversion_goal_evidence import ConversionGoalEvidenceService
from products.marketing_analytics.backend.services.conversion_recommendations import ConversionRecommendationService

QUEUE = (
    "products.marketing_analytics.backend.tasks.conversion_recommendations.generate_conversion_recommendations.delay"
)


@time_machine.travel("2026-10-01T12:00:00Z", tick=False)
class TestConversionRecommendations(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.base = f"/api/projects/{self.team.pk}/marketing_analytics/conversion_recommendations"
        self.flags = patch("products.marketing_analytics.backend.api.feature_enabled_or_false", return_value=True)
        self.flags.start()
        self.addCleanup(self.flags.stop)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.worker_flags = patch(
            "products.marketing_analytics.backend.services.conversion_recommendations.feature_enabled_or_false",
            return_value=True,
        )
        self.worker_flags.start()
        self.addCleanup(self.worker_flags.stop)

    @parameterized.expand([("consent",), ("flag",)])
    def test_generation_rechecks_consent_and_flag_before_worker_data_access(self, denied: str) -> None:
        with patch(QUEUE), self.captureOnCommitCallbacks(execute=True):
            run_id = self.client.post(self.base + "/start", {}).json()["latest_run"]["id"]
        if denied == "consent":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        else:
            self.worker_flags.stop()
            self.worker_flags = patch(
                "products.marketing_analytics.backend.services.conversion_recommendations.feature_enabled_or_false",
                return_value=False,
            )
            self.worker_flags.start()
            self.addCleanup(self.worker_flags.stop)
        state = self.client.get(self.base).json()
        self.assertFalse(state["can_generate"])
        self.assertTrue(state["generation_disabled_reason"])
        self.assertEqual(self.client.post(self.base + "/start", {"refresh": True}).status_code, 403)
        with patch.object(ConversionRecommendationService, "generate") as generate:
            ConversionRecommendationService(self.team, self.user).execute(run_id)
        generate.assert_not_called()
        self.assertEqual(ConversionRecommendationRun.objects.for_team(self.team.pk).get(pk=run_id).status, "failed")

    def test_initial_analysis_runs_once_and_explicit_update_keeps_previous_results(self) -> None:
        with patch(QUEUE) as enqueue, self.captureOnCommitCallbacks(execute=True):
            self.assertIsNone(self.client.get(self.base).json()["latest_run"])
            first = self.client.post(self.base + "/start", {"refresh": False}).json()["latest_run"]
            duplicate = self.client.post(self.base + "/start", {"refresh": False}).json()["latest_run"]
        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(first["lookback_days"], 30)
        self.assertEqual(enqueue.call_count, 1)
        runs = ConversionRecommendationRun.objects.for_team(self.team.pk)
        runs.filter(pk=first["id"]).update(
            status="completed", results={"recommendations": [], "limitations": ["No suitable sources"]}
        )
        with (
            time_machine.travel("2026-10-01T12:01:00Z", tick=False),
            patch(QUEUE) as enqueue,
            self.captureOnCommitCallbacks(execute=True),
        ):
            cached = self.client.post(self.base + "/start", {"refresh": False}).json()
            updated = self.client.post(self.base + "/start", {"refresh": True}).json()
        self.assertEqual(cached["latest_run"]["id"], first["id"])
        self.assertNotEqual(updated["latest_run"]["id"], first["id"])
        self.assertEqual(updated["latest_run"]["lookback_days"], 14)
        self.assertEqual(updated["result_run"]["id"], first["id"])
        self.assertEqual(updated["results"]["limitations"], ["No suitable sources"])
        self.assertEqual(enqueue.call_count, 1)

    def test_interrupted_run_does_not_restart_on_navigation(self) -> None:
        with patch(QUEUE), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.base + "/start", {"refresh": False})
        run_id = response.json()["latest_run"]["id"]
        ConversionRecommendationRun.objects.for_team(self.team.pk).filter(pk=run_id).update(
            created_at=timezone.now() - timedelta(minutes=6)
        )
        with patch(QUEUE) as enqueue:
            response = self.client.get(self.base).json()
            self.assertEqual(response["latest_run"]["status"], "failed")
            response = self.client.post(self.base + "/start", {"refresh": False}).json()
        self.assertEqual(response["latest_run"]["id"], run_id)
        enqueue.assert_not_called()

    def test_dispatch_failure_is_visible_and_read_does_not_retry(self) -> None:
        with patch(QUEUE, side_effect=ConnectionError("offline")), self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.base + "/start", {"refresh": False})
        with patch(QUEUE) as enqueue:
            response = self.client.get(self.base).json()
        self.assertEqual(response["latest_run"]["status"], "failed")
        self.assertIn("Could not start", response["latest_run"]["error"])
        enqueue.assert_not_called()

    def test_flag_membership_and_project_scope_are_enforced(self) -> None:
        self.organization.available_product_features = []
        self.organization.save(update_fields=["available_product_features"])
        with patch("products.marketing_analytics.backend.api.feature_enabled_or_false", return_value=False):
            self.assertEqual(self.client.get(self.base).status_code, 404)
            self.assertEqual(self.client.post(self.base + "/start", {}).status_code, 404)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        with self.captureOnCommitCallbacks(execute=True):
            self.organization_membership.save()
        self.assertFalse(self.client.get(self.base).json()["can_generate"])
        self.assertEqual(self.client.post(self.base + "/start", {}).status_code, 403)
        other = Team.objects.create(organization=self.organization)
        now = timezone.now()
        ConversionRecommendationRun.objects.for_team(other.pk).create(
            team_id=other.pk,
            requested_by=self.user,
            lookback_days=30,
            date_from=now - timedelta(days=30),
            date_to=now,
        )
        self.assertIsNone(self.client.get(self.base).json()["latest_run"])

    @parameterized.expand(
        [
            ("read_scope", "marketing_analytics:read", False, 403),
            ("write_scope", "marketing_analytics:write", False, 200),
            ("read_only_mcp", "marketing_analytics:write", True, 403),
        ]
    )
    def test_generation_requires_write_access(
        self, _name: str, scope: str, read_only_mcp: bool, expected_status: int
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS, "name": "Security settings"}
        ]
        self.organization.read_only_mcp_access = read_only_mcp
        self.organization.save(update_fields=["available_product_features", "read_only_mcp_access"])
        key = self.create_personal_api_key_with_scopes([scope])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}", HTTP_USER_AGENT=MCP_USER_AGENT_MARKER)

        self.assertEqual(self.client.get(self.base).status_code, 200)
        with patch(QUEUE) as enqueue, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.base + "/start", {"refresh": True})

        self.assertEqual(response.status_code, expected_status, response.content)
        expected_runs = 1 if expected_status == 200 else 0
        self.assertEqual(ConversionRecommendationRun.objects.for_team(self.team.pk).count(), expected_runs)
        self.assertEqual(enqueue.call_count, expected_runs)

    @parameterized.expand([("amount", True), ("invented_amount", False)])
    def test_revenue_proposal_requires_observed_amount_and_keeps_business_questions(
        self, amount: str, has_draft: bool
    ) -> None:
        now = timezone.now()
        run = ConversionRecommendationRun.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            requested_by=self.user,
            lookback_days=30,
            date_from=now - timedelta(days=30),
            date_to=now,
        )
        EventProperty.objects.create(team=self.team, event="order_settled", property="amount")
        PropertyDefinition.objects.create(
            team=self.team, name="amount", type=PropertyDefinition.Type.EVENT, is_numerical=True
        )
        client = MagicMock()
        client.with_options.return_value = client
        client.__enter__.return_value = client
        client.messages.create.return_value = SimpleNamespace(
            content=[
                ToolUseBlock(
                    type="tool_use",
                    id="synthetic",
                    name="recommendations",
                    input={
                        "recommendations": [
                            {
                                "source_ref": "event:order_settled",
                                "name": "Settled orders",
                                "reason": "This may record completed payments.",
                                "intent": "revenue",
                                "amount_property": amount,
                                "questions": [],
                            }
                        ]
                    },
                )
            ]
        )

        def query_with_required_tags(*args: object, **kwargs: object) -> SimpleNamespace:
            self.assertEqual(get_query_tag_value("product"), Product.MARKETING_ANALYTICS)
            self.assertEqual(get_query_tag_value("feature"), Feature.HEALTH_CHECK)
            self.assertEqual(get_query_tag_value("team_id"), self.team.pk)
            return SimpleNamespace(results=[["order_settled", 20, 10]])

        with (
            patch(
                "products.marketing_analytics.backend.services.conversion_recommendations.execute_hogql_query",
                side_effect=query_with_required_tags,
            ),
            patch("posthog.llm.gateway_client.build_ai_gateway_anthropic_client", return_value=client),
        ):
            ConversionRecommendationService(self.team, self.user).execute(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        proposal = run.results["recommendations"][0]
        self.assertEqual(proposal["draft"] is not None, has_draft)
        self.assertEqual(proposal["candidate"]["count"], 20)
        self.assertEqual(proposal["state"], "needs_decision")
        self.assertTrue(proposal["questions"])
        self.assertEqual(self.team.marketing_analytics_config.conversion_goals, [])

    @parameterized.expand([("duplicate", "event:order_settled", "completed"), ("unknown", "event:unknown", "failed")])
    def test_duplicate_recommendations_keep_first_and_unknown_sources_fail(
        self, _name: str, second_source: str, expected_status: str
    ) -> None:
        now = timezone.now()
        run = ConversionRecommendationRun.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            requested_by=self.user,
            lookback_days=30,
            date_from=now - timedelta(days=30),
            date_to=now,
        )
        client = MagicMock()
        client.with_options.return_value = client
        client.__enter__.return_value = client
        client.messages.create.return_value = SimpleNamespace(
            content=[
                ToolUseBlock(
                    type="tool_use",
                    id="synthetic",
                    name="recommendations",
                    input={
                        "recommendations": [
                            {
                                "source_ref": source,
                                "name": name,
                                "reason": "Review this business milestone.",
                                "intent": "conversion",
                                "questions": [],
                            }
                            for source, name in [
                                ("event:order_settled", "Settled orders"),
                                (second_source, "Repeated orders"),
                                ("event:trial_started", "Trial starts"),
                            ]
                        ]
                    },
                )
            ]
        )
        with (
            patch(
                "products.marketing_analytics.backend.services.conversion_recommendations.execute_hogql_query",
                return_value=SimpleNamespace(results=[["order_settled", 20, 10], ["trial_started", 15, 12]]),
            ),
            patch("posthog.llm.gateway_client.build_ai_gateway_anthropic_client", return_value=client),
        ):
            ConversionRecommendationService(self.team, self.user).execute(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, expected_status)
        if expected_status == "completed":
            self.assertEqual(
                [(item["source_ref"], item["name"]) for item in run.results["recommendations"]],
                [("event:order_settled", "Settled orders"), ("event:trial_started", "Trial starts")],
            )
        else:
            self.assertEqual(run.results, {})
            self.assertTrue(run.error)


@time_machine.travel("2026-10-01T12:00:00Z", tick=False)
class TestValidatedConversionApplication(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.base = f"/api/projects/{self.team.pk}/marketing_analytics/conversion_goals/apply"
        self.flags = patch("products.marketing_analytics.backend.api.feature_enabled_or_false", return_value=True)
        self.flags.start()
        self.addCleanup(self.flags.stop)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.worker_flags = patch(
            "products.marketing_analytics.backend.services.conversion_recommendations.feature_enabled_or_false",
            return_value=True,
        )
        self.worker_flags.start()
        self.addCleanup(self.worker_flags.stop)
        self.config = get_or_create_team_extension(self.team, TeamMarketingAnalyticsConfig)
        now = timezone.now()
        serializer = ConversionGoalPreviewSerializer(
            data={
                "goal": {
                    "kind": "EventsNode",
                    "event": "order_settled",
                    "conversion_goal_name": "Settled orders",
                    "schema_map": {},
                    "math": "total",
                },
                "date_from": (now - timedelta(days=14)).isoformat(),
                "date_to": now.isoformat(),
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        goal = serializer.validated_data["goal"]
        service = ConversionGoalEvidenceService(self.team, self.user)
        self.evidence = service.record(goal, service.context_hash(goal))
        self.payload = {"goal": self.evidence.goal, "preview_ref": str(self.evidence.id), "definition_confirmed": True}

    def test_record_cleans_expired_unused_evidence_and_preserves_applied_receipts(self) -> None:
        records = ConversionGoalPreviewEvidence.objects.for_team(self.team.pk)
        records.filter(pk=self.evidence.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        applied = records.create(
            team_id=self.team.pk,
            requested_by=self.user,
            goal=self.evidence.goal,
            context_hash=self.evidence.context_hash,
            expires_at=timezone.now() - timedelta(minutes=1),
            applied_goal=self.evidence.goal,
        )
        serializer = ConversionGoalPreviewSerializer(
            data={
                "goal": self.evidence.goal,
                "date_from": (timezone.now() - timedelta(days=14)).isoformat(),
                "date_to": timezone.now().isoformat(),
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        service = ConversionGoalEvidenceService(self.team, self.user)
        goal = serializer.validated_data["goal"]
        fresh = service.record(goal, service.context_hash(goal))
        self.assertFalse(records.filter(pk=self.evidence.pk).exists())
        self.assertTrue(records.filter(pk=applied.pk).exists())
        self.assertTrue(records.filter(pk=fresh.pk).exists())

    def test_retry_after_lost_response_returns_one_goal_even_after_expiry(self) -> None:
        first = self.client.post(self.base, self.payload).json()
        ConversionGoalPreviewEvidence.objects.for_team(self.team.pk).filter(pk=self.evidence.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        retry = self.client.post(self.base, self.payload)
        self.assertEqual(retry.status_code, 200, retry.json())
        self.assertEqual(retry.json(), first)
        self.assertEqual(len(first["conversion_goals"]), 1)
        config = self.team.marketing_analytics_config
        config._conversion_goals = []
        config.save()
        self.assertEqual(self.client.post(self.base, self.payload).status_code, 409)
        config.refresh_from_db()
        self.assertEqual(config.conversion_goals, [])

    @parameterized.expand(
        [("edited",), ("expired",), ("config",), ("confirmation",), ("other_project",), ("other_user",)]
    )
    def test_rejects_unreviewed_or_stale_application(self, change: str) -> None:
        expected = 409
        if change == "edited":
            self.payload["goal"] = {**self.payload["goal"], "event": "another_event"}
        elif change == "expired":
            self.evidence.expires_at = timezone.now() - timedelta(seconds=1)
            self.evidence.save(update_fields=["expires_at"])
        elif change == "config":
            config = self.team.marketing_analytics_config
            config.attribution_window_days = 7
            config.save()
        elif change == "confirmation":
            self.payload["definition_confirmed"] = False
            expected = 400
        elif change == "other_project":
            other = Team.objects.create(organization=self.organization)
            self.base = f"/api/projects/{other.pk}/marketing_analytics/conversion_goals/apply"
            expected = 404
        elif change == "other_user":
            self.evidence.requested_by = User.objects.create_and_join(
                self.organization, "second@example.com", "password"
            )
            self.evidence.save(update_fields=["requested_by"])
            expected = 404
        response = self.client.post(self.base, self.payload)
        self.assertEqual(response.status_code, expected, response.json())
        config = self.team.marketing_analytics_config
        config.refresh_from_db()
        self.assertEqual(config.conversion_goals, [])
