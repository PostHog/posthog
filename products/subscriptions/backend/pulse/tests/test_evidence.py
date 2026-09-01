from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test import override_settings
from django.utils import timezone

from posthog.egress.firecrawl.client import FirecrawlScrape, FirecrawlSearchFailed, FirecrawlSearchResult
from posthog.egress.firecrawl.transport import FirecrawlEgressBudgetExhausted
from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.subscriptions.backend.facade.pulse import (
    PulseEvidenceConflict,
    PulseEvidenceNotFound,
    PulsePublicResearchUnavailable,
    _build_activity_config_snapshot,
    begin_evidence_tool_call,
    complete_evidence_tool_call,
    fail_evidence_tool_call,
    prepare_pulse_workflow,
    purge_expired_evidence_raw_bodies,
    read_evidence_raw_body,
    research_public_context,
)
from products.subscriptions.backend.pulse.contracts import GoalNormalizationResult
from products.subscriptions.backend.pulse.dispatch_snapshot import (
    ScheduledPulseEligibilityInput,
    build_scheduled_proactive_dispatch_snapshot,
)
from products.subscriptions.backend.pulse.models import (
    EvidenceRawBody,
    EvidenceToolCall,
    ProactiveSubscriptionConfig,
    PulseRun,
)
from products.subscriptions.backend.pulse.temporal.inputs import ProactiveDispatchSnapshot, PulseStartInput

from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


class TestPulseEvidenceFacade(BaseTest):
    def _run(
        self,
        *,
        team: Team | None = None,
        subscription_id: int | None = None,
        contexts: list[dict[str, int]] | None = None,
    ) -> PulseRun:
        resolved_team = team or self.team
        subscription = create_subscription(team=resolved_team, created_by=self.user, prompt="Find an improvement.")
        return PulseRun.objects.create(
            team=resolved_team,
            subscription_id=subscription_id or subscription.id,
            delivery_id=uuid4(),
            config_snapshot={"actor_id": self.user.id, "contexts": contexts or []},
            report_snapshot_ref="reports/evidence",
        )

    def _begin(
        self,
        run: PulseRun,
        *,
        call_id: str = "call-1",
        tool_name: str = "query",
        arguments: object = {"query": "select 1"},
        expires_at=None,
    ):
        return begin_evidence_tool_call(
            team_id=self.team.id,
            team=self.team,
            user=self.user,
            run_id=run.id,
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_schema_version="v1",
            arguments=arguments,
            actor_id=self.user.id,
            raw_expires_at=expires_at or timezone.now() + timedelta(days=1),
        )

    def test_authorized_round_trip_encrypts_raw_body_and_retains_metadata(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            begun = self._begin(run)
            completed = complete_evidence_tool_call(
                team_id=self.team.id,
                team=self.team,
                user=self.user,
                run_id=run.id,
                tool_call_id="call-1",
                result={"rows": 1},
            )
            raw_content = read_evidence_raw_body(
                team_id=self.team.id, team=self.team, user=self.user, evidence_id=begun.id
            )
            raw = EvidenceRawBody.objects.get(tool_call_id=begun.id)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT encrypted_arguments FROM subscriptions_evidencerawbody WHERE id = %s", [str(raw.id)]
                )
                stored = cursor.fetchone()[0]

        assert begun.id == completed.id
        assert raw_content.encrypted_arguments == '{"query":"select 1"}'
        assert raw_content.encrypted_result == '{"rows":1}'
        assert "select 1" not in stored
        assert (
            EvidenceToolCall.objects.for_team(self.team.id).get(id=begun.id).normalized_result_ref.startswith("sha256:")
        )

    def test_begin_retry_rejects_a_conflicting_binding(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            expires_at = timezone.now() + timedelta(days=1)
            first = self._begin(run, expires_at=expires_at)
            assert self._begin(run, expires_at=expires_at).id == first.id
            with self.assertRaises(PulseEvidenceConflict):
                self._begin(run, arguments={"query": "different"}, expires_at=expires_at)

    def test_run_actor_binding_is_checked_before_evidence_is_persisted(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            run.config_snapshot = {"actor_id": self.user.id + 1, "contexts": []}
            run.save(update_fields=["config_snapshot"])

            with self.assertRaises(PulseEvidenceNotFound):
                self._begin(run)

            assert not EvidenceToolCall.objects.for_team(self.team.id).filter(run=run).exists()

    def test_tool_call_budget_is_atomic_and_retry_does_not_consume_another_slot(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            run.config_snapshot = {
                "actor_id": self.user.id,
                "contexts": [],
                "limits": {"max_tool_calls": 1},
            }
            run.save(update_fields=["config_snapshot"])
            expires_at = timezone.now() + timedelta(days=1)

            first = self._begin(run, call_id="first", expires_at=expires_at)
            assert self._begin(run, call_id="first", expires_at=expires_at).id == first.id
            with self.assertRaisesRegex(PulseEvidenceConflict, "tool-call budget"):
                self._begin(run, call_id="second", expires_at=expires_at)

    def test_public_research_budget_is_separate_and_retry_safe(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            run.config_snapshot = {
                "actor_id": self.user.id,
                "contexts": [],
                "limits": {"max_tool_calls": 3, "max_public_research_calls": 1},
            }
            run.save(update_fields=["config_snapshot"])
            expires_at = timezone.now() + timedelta(days=1)

            first = self._begin(
                run,
                call_id="research-first",
                tool_name="pulse_public_research",
                expires_at=expires_at,
            )
            assert (
                self._begin(
                    run,
                    call_id="research-first",
                    tool_name="pulse_public_research",
                    expires_at=expires_at,
                ).id
                == first.id
            )
            self._begin(run, call_id="ordinary-tool", expires_at=expires_at)
            with self.assertRaisesRegex(PulseEvidenceConflict, "public-research budget"):
                self._begin(
                    run,
                    call_id="research-second",
                    tool_name="pulse_public_research",
                    expires_at=expires_at,
                )

    def test_stale_public_research_claim_can_be_recovered_after_provider_deadline(self) -> None:
        arguments = {
            "topic": "activation_best_practices",
            "query": "software product activation best practices",
        }
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            expires_at = timezone.now() + timedelta(days=1)
            claimed = self._begin(
                run,
                call_id="abandoned-research",
                tool_name="pulse_public_research",
                arguments=arguments,
                expires_at=expires_at,
            )
            concurrent_retry = self._begin(
                run,
                call_id="abandoned-research",
                tool_name="pulse_public_research",
                arguments=arguments,
                expires_at=expires_at,
            )
            call = EvidenceToolCall.objects.get(id=claimed.id)
            call.started_at = timezone.now() - timedelta(seconds=46)
            call.save(update_fields=["started_at"])
            recovered = self._begin(
                run,
                call_id="abandoned-research",
                tool_name="pulse_public_research",
                arguments=arguments,
                expires_at=expires_at,
            )
            with self.assertRaisesRegex(PulseEvidenceConflict, "lease is no longer current"):
                complete_evidence_tool_call(
                    team_id=self.team.id,
                    team=self.team,
                    user=self.user,
                    run_id=run.id,
                    tool_call_id="abandoned-research",
                    result={"citation": "stale"},
                    execution_lease_started_at=claimed.execution_lease_started_at,
                )
            with self.assertRaisesRegex(PulseEvidenceConflict, "lease is no longer current"):
                fail_evidence_tool_call(
                    team_id=self.team.id,
                    team=self.team,
                    user=self.user,
                    run_id=run.id,
                    tool_call_id="abandoned-research",
                    error_class="StaleOwnerFailure",
                    execution_lease_started_at=claimed.execution_lease_started_at,
                )
            completed = complete_evidence_tool_call(
                team_id=self.team.id,
                team=self.team,
                user=self.user,
                run_id=run.id,
                tool_call_id="abandoned-research",
                result={"citation": "current"},
                execution_lease_started_at=recovered.execution_lease_started_at,
            )

        assert claimed.execution_claimed is True
        assert concurrent_retry.execution_claimed is False
        assert recovered.execution_claimed is True
        assert recovered.execution_lease_started_at != claimed.execution_lease_started_at
        assert completed.completed_at is not None

    def test_legacy_v1_dispatch_snapshot_keeps_the_run_but_disables_unrestricted_research(self) -> None:
        subscription = create_subscription(team=self.team, created_by=self.user, prompt="Find an improvement.")
        input = PulseStartInput(
            team_id=self.team.id,
            subscription_id=subscription.id,
            delivery_id=uuid4(),
            report_snapshot_ref="reports/legacy-research",
            proactive_snapshot=ProactiveDispatchSnapshot(
                version=1,
                enabled=True,
                config_snapshot_ref="subscriptions/pulse/dispatch-snapshots/v1/legacy.json",
                wall_clock_budget_seconds=3600,
                finalization_margin_seconds=300,
            ),
        )
        legacy_subject_id = str(uuid4())
        dispatch = {
            "version": 1,
            "prompt": "Find an improvement.",
            "contexts": [],
            "repository": None,
            "repository_grant_id": None,
            "repository_grant": None,
            "public_research_subject_id": legacy_subject_id,
            "public_research_subject": {"id": legacy_subject_id},
            "flags": {"allow_public_research": True},
            "limits": {},
        }

        with patch(
            "products.subscriptions.backend.facade.pulse.normalize_goal_with_model",
            return_value=GoalNormalizationResult(
                goal_statement="Find an improvement.",
                decision_constraints=[],
                prompt_version="v1",
                model_version=None,
                valid=True,
            ),
        ):
            snapshot = _build_activity_config_snapshot(
                input=input,
                dispatch=dispatch,
                team=self.team,
                actor=self.user,
            )

        assert snapshot["public_research_enabled"] is False
        flags = snapshot["flags"]
        assert isinstance(flags, dict)
        assert flags["allow_public_research"] is False

    @override_settings(
        PULSE_PROACTIVE_ENABLED=True,
        PULSE_PUBLIC_RESEARCH_ENABLED=True,
        FIRECRAWL_API_KEY="test-firecrawl-key",
    )
    def test_prepared_run_preserves_public_research_consent_for_authorization(self) -> None:
        stored_snapshots: dict[str, bytes] = {}

        def read_snapshot(key: str, **_kwargs: object) -> bytes | None:
            return stored_snapshots.get(key)

        def write_snapshot(key: str, contents: bytes, **_kwargs: object) -> None:
            stored_snapshots[key] = contents

        with team_scope(self.team.id, canonical=True):
            subscription = create_subscription(team=self.team, created_by=self.user, prompt="Find an improvement.")
            ProactiveSubscriptionConfig.objects.create(
                team=self.team,
                subscription_id=subscription.id,
                enabled=True,
                public_research_enabled=True,
            )
            eligibility = ScheduledPulseEligibilityInput(
                team_id=self.team.id,
                subscription_id=subscription.id,
                prompt="Find an improvement.",
                contexts=[],
                actor_id=self.user.id,
                integration_id=None,
            )
            with (
                patch(
                    "products.subscriptions.backend.pulse.dispatch_snapshot.subscription_snapshot_contexts_are_authorized",
                    return_value=True,
                ),
                patch("posthog.storage.object_storage.read_bytes", side_effect=read_snapshot),
                patch("posthog.storage.object_storage.write", side_effect=write_snapshot),
                patch(
                    "products.subscriptions.backend.facade.pulse.normalize_goal_with_model",
                    return_value=GoalNormalizationResult(
                        goal_statement="Find an improvement.",
                        decision_constraints=[],
                        prompt_version="v1",
                        model_version=None,
                        valid=True,
                    ),
                ),
            ):
                dispatch = build_scheduled_proactive_dispatch_snapshot(eligibility)
                assert dispatch is not None
                prepared = prepare_pulse_workflow(
                    PulseStartInput(
                        team_id=self.team.id,
                        subscription_id=subscription.id,
                        delivery_id=uuid4(),
                        report_snapshot_ref="reports/prepared-research",
                        proactive_snapshot=dispatch,
                    )
                )

            assert prepared is not None
            run = PulseRun.objects.for_team(self.team.id).get(id=prepared.pulse_run_id)
            assert run.config_snapshot["public_research_enabled"] is True
            assert run.config_snapshot["flags"]["allow_public_research"] is True

            search_result = FirecrawlSearchResult(
                url="https://research.example.com/market",
                title="Market research",
                description="A public summary",
            )
            scrape_result = FirecrawlScrape(
                url=search_result.url,
                title=search_result.title,
                markdown="Detailed public research",
            )
            with (
                patch(
                    "products.subscriptions.backend.facade.pulse.search_public_web",
                    return_value=(search_result,),
                ),
                patch(
                    "products.subscriptions.backend.facade.pulse.scrape_public_url",
                    return_value=scrape_result,
                ),
            ):
                citation = research_public_context(
                    team_id=self.team.id,
                    team=self.team,
                    user=self.user,
                    run_id=run.id,
                    topic="product_analytics_market_trends",
                    tool_call_id="prepared-research",
                    raw_expires_at=timezone.now() + timedelta(days=1),
                )

        assert citation.canonical_url == "https://research.example.com/market"

    def test_complete_retry_rejects_a_conflicting_result(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            expires_at = timezone.now() + timedelta(days=1)
            self._begin(run, expires_at=expires_at)
            complete_evidence_tool_call(
                team_id=self.team.id,
                team=self.team,
                user=self.user,
                run_id=run.id,
                tool_call_id="call-1",
                result={"rows": 1},
            )
            assert (
                complete_evidence_tool_call(
                    team_id=self.team.id,
                    team=self.team,
                    user=self.user,
                    run_id=run.id,
                    tool_call_id="call-1",
                    result={"rows": 1},
                ).completed_at
                is not None
            )
            with self.assertRaises(PulseEvidenceConflict):
                complete_evidence_tool_call(
                    team_id=self.team.id,
                    team=self.team,
                    user=self.user,
                    run_id=run.id,
                    tool_call_id="call-1",
                    result={"rows": 2},
                )

    def test_failure_retry_is_idempotent_and_cannot_be_replaced_with_a_result(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            self._begin(run)
            failed = fail_evidence_tool_call(
                team_id=self.team.id,
                team=self.team,
                user=self.user,
                run_id=run.id,
                tool_call_id="call-1",
                error_class="ProviderUnavailable",
            )
            retried = fail_evidence_tool_call(
                team_id=self.team.id,
                team=self.team,
                user=self.user,
                run_id=run.id,
                tool_call_id="call-1",
                error_class="ProviderUnavailable",
            )
            with self.assertRaises(PulseEvidenceConflict):
                complete_evidence_tool_call(
                    team_id=self.team.id,
                    team=self.team,
                    user=self.user,
                    run_id=run.id,
                    tool_call_id="call-1",
                    result={"rows": 1},
                )

        assert failed.id == retried.id
        assert failed.error_class == "ProviderUnavailable"

    @override_settings(PULSE_PUBLIC_RESEARCH_ENABLED=True)
    def test_public_research_is_evidenced_and_retries_without_another_provider_call(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            run.config_snapshot = {
                "actor_id": self.user.id,
                "contexts": [],
                "public_research_enabled": True,
                "flags": {"allow_public_research": True},
            }
            run.save(update_fields=["config_snapshot"])
            search_result = FirecrawlSearchResult(
                url="https://research.example.com/market",
                title="Market research",
                description="A public summary",
            )
            scrape_result = FirecrawlScrape(
                url=search_result.url,
                title=search_result.title,
                markdown="Detailed public research",
            )
            expires_at = timezone.now() + timedelta(days=1)
            with (
                patch(
                    "products.subscriptions.backend.facade.pulse.search_public_web",
                    return_value=(search_result,),
                ) as search,
                patch(
                    "products.subscriptions.backend.facade.pulse.scrape_public_url",
                    return_value=scrape_result,
                ) as scrape,
            ):
                first = research_public_context(
                    team_id=self.team.id,
                    team=self.team,
                    user=self.user,
                    run_id=run.id,
                    topic="product_analytics_market_trends",
                    tool_call_id="research-1",
                    raw_expires_at=expires_at,
                )
                retried = research_public_context(
                    team_id=self.team.id,
                    team=self.team,
                    user=self.user,
                    run_id=run.id,
                    topic="product_analytics_market_trends",
                    tool_call_id="research-1",
                    raw_expires_at=expires_at,
                )
            raw_content = read_evidence_raw_body(
                team_id=self.team.id,
                team=self.team,
                user=self.user,
                evidence_id=first.evidence_id,
            )

        assert retried == first
        assert first.excerpt == "Detailed public research"
        assert first.evidence_id is not None
        assert '"canonical_url":"https://research.example.com/market"' in (raw_content.encrypted_result or "")
        search.assert_called_once()
        scrape.assert_called_once()

    @override_settings(PULSE_PUBLIC_RESEARCH_ENABLED=True)
    def test_public_research_uses_the_search_description_when_scraping_is_shed(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            run.config_snapshot = {
                "actor_id": self.user.id,
                "contexts": [],
                "public_research_enabled": True,
                "flags": {"allow_public_research": True},
            }
            run.save(update_fields=["config_snapshot"])
            search_result = FirecrawlSearchResult(
                url="https://research.example.com/market",
                title="Market research",
                description="A bounded public search summary",
            )
            with (
                patch(
                    "products.subscriptions.backend.facade.pulse.search_public_web",
                    return_value=(search_result,),
                ),
                patch(
                    "products.subscriptions.backend.facade.pulse.scrape_public_url",
                    side_effect=FirecrawlEgressBudgetExhausted,
                ),
            ):
                citation = research_public_context(
                    team_id=self.team.id,
                    team=self.team,
                    user=self.user,
                    run_id=run.id,
                    topic="product_analytics_market_trends",
                    tool_call_id="research-scrape-shed",
                    raw_expires_at=timezone.now() + timedelta(days=1),
                )

        assert citation.canonical_url == search_result.url
        assert citation.excerpt == "A bounded public search summary"

    @override_settings(PULSE_PUBLIC_RESEARCH_ENABLED=True)
    def test_public_research_records_a_redacted_provider_failure_once(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            run.config_snapshot = {
                "actor_id": self.user.id,
                "contexts": [],
                "public_research_enabled": True,
                "flags": {"allow_public_research": True},
            }
            run.save(update_fields=["config_snapshot"])
            expires_at = timezone.now() + timedelta(days=1)
            with patch(
                "products.subscriptions.backend.facade.pulse.search_public_web",
                side_effect=FirecrawlSearchFailed("provider detail must not be stored"),
            ) as search:
                for _ in range(2):
                    with self.assertRaises(PulsePublicResearchUnavailable):
                        research_public_context(
                            team_id=self.team.id,
                            team=self.team,
                            user=self.user,
                            run_id=run.id,
                            topic="product_analytics_market_trends",
                            tool_call_id="research-failure",
                            raw_expires_at=expires_at,
                        )
            call = EvidenceToolCall.objects.get(run=run, tool_call_id="research-failure")
            raw_content = read_evidence_raw_body(
                team_id=self.team.id,
                team=self.team,
                user=self.user,
                evidence_id=call.id,
            )

        assert call.error_class == "FirecrawlSearchFailed"
        assert raw_content.encrypted_result is None
        search.assert_called_once()

    def test_actor_context_and_team_are_authorized_and_expiry_is_enforced(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            evidence = self._begin(run, expires_at=timezone.now() + timedelta(days=90))
            call = EvidenceToolCall.objects.get(id=evidence.id)
            assert call.actor_id == self.user.id
            assert call.raw_expires_at is not None
            assert call.raw_expires_at <= timezone.now() + timedelta(days=30, seconds=1)
            call.raw_expires_at = timezone.now() - timedelta(seconds=1)
            call.save(update_fields=["raw_expires_at"])
            with self.assertRaises(PulseEvidenceNotFound):
                read_evidence_raw_body(team_id=self.team.id, team=self.team, user=self.user, evidence_id=evidence.id)
        with team_scope(other_team.id, canonical=True), self.assertRaises(PulseEvidenceNotFound):
            read_evidence_raw_body(team_id=other_team.id, team=other_team, user=self.user, evidence_id=evidence.id)

    def test_begin_rejects_a_spoofed_actor_or_unviewable_snapshot_context(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            with self.assertRaises(PulseEvidenceNotFound):
                begin_evidence_tool_call(
                    team_id=self.team.id,
                    team=self.team,
                    user=self.user,
                    run_id=run.id,
                    tool_call_id="spoofed-actor",
                    tool_name="query",
                    tool_schema_version="v1",
                    arguments={},
                    actor_id=self.user.id + 1,
                    raw_expires_at=timezone.now() + timedelta(days=1),
                )
            inaccessible = self._run(contexts=[{"insight_id": 999999999}])
            with self.assertRaises(PulseEvidenceNotFound):
                self._begin(inaccessible, call_id="blocked-context")

    def test_purge_deletes_raw_body_once_but_keeps_audit_metadata(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._run()
            evidence = self._begin(run)
            other_evidence = self._begin(run, call_id="call-2")
            EvidenceToolCall.objects.filter(id__in=[evidence.id, other_evidence.id]).update(
                raw_expires_at=timezone.now() - timedelta(seconds=1)
            )
            assert purge_expired_evidence_raw_bodies(batch_size=1) == 1
            assert (
                EvidenceToolCall.objects.filter(
                    id__in=[evidence.id, other_evidence.id], purged_at__isnull=False
                ).count()
                == 1
            )
            assert purge_expired_evidence_raw_bodies(batch_size=1) == 1
            assert purge_expired_evidence_raw_bodies() == 0
            call = EvidenceToolCall.objects.get(id=evidence.id)
            assert call.purged_at is not None
            assert call.raw_arguments_ref is None
            assert not EvidenceRawBody.objects.filter(tool_call_id=evidence.id).exists()
