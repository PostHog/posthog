import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from django.apps import apps
from django.test import override_settings
from django.utils import timezone

from posthog.models import Team

from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.facade import proactive
from products.subscriptions.backend.facade.contracts import (
    Recommendation,
    RecommendationCitation,
    RecommendationGenerationHandle,
    RecommendationGenerationInput,
    RecommendationResult,
)
from products.subscriptions.backend.facade.proactive import (
    claim_recommendation_run,
    finalize_recommendation_run,
    get_proactive_config,
    get_proactive_configuration_options,
    read_recommendation_appendix,
    recent_recommendation_memory,
)
from products.subscriptions.backend.models import (
    ProactivePreparedArtifact,
    ProactiveRecommendation,
    ProactiveRecommendationOutcome,
    ProactiveRecommendationRun,
)
from products.tasks.backend.facade.repository_authorization import (
    AuthorizableRepository,
    ResolvedStagedRepositoryBinding,
)
from products.tasks.backend.facade.staged_evidence import CompletedMCPCallEvidence
from products.tasks.backend.facade.staged_execution import StagedRepositoryBinding


def _recommendation(
    semantic_key: str,
    *,
    title: str | None = None,
    measurement_call_id: str | None = None,
    metric_direction: str = "increase",
) -> Recommendation:
    return Recommendation(
        kind="investigation",
        title=title or f"Check {semantic_key}",
        rationale="Activation fell",
        target="activation",
        why_now="This week",
        confidence=0.8,
        effort="small",
        metric_name="activation rate",
        metric_direction=metric_direction,
        expected_metric_movement="5%",
        citation_ids=("report", "mcp:insight") if measurement_call_id else ("report",),
        semantic_key=semantic_key,
        measurement_call_id=measurement_call_id,
    )


def _result(
    *recommendations: Recommendation, completed_mcp_calls: tuple[CompletedMCPCallEvidence, ...] = ()
) -> RecommendationResult:
    return RecommendationResult(
        recommendations=recommendations,
        citations=(
            RecommendationCitation(id="report", title="Subscription report"),
            RecommendationCitation(id="mcp:insight", title="PostHog MCP: insight-query"),
        ),
        completed_mcp_calls=completed_mcp_calls,
    )


def _measurement_call(*, insight_id: int, short_id: str) -> CompletedMCPCallEvidence:
    return CompletedMCPCallEvidence(
        citation_id="mcp:insight",
        tool_name="insight-query",
        arguments={"insightId": short_id, "output_format": "json"},
        result={
            "insight": {"id": insight_id, "short_id": short_id},
            "query": {
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": "signed_up", "math": "total"}],
                "interval": "day",
                "dateRange": {"date_from": "2026-09-01", "date_to": "2026-09-07"},
            },
            "results": [{"count": 0}],
        },
    )


@pytest.mark.django_db
def test_proactive_subscription_config_is_a_team_scoped_record(team) -> None:
    """A config must be independently scoped, rather than stored in an Exports JSON field."""
    config_model = apps.get_model("subscriptions", "ProactiveSubscriptionConfig")

    config = config_model.objects.for_team(team.id).create(team_id=team.id, subscription_id=123, enabled=True)

    assert config.team_id == team.id
    assert config.subscription_id == 123
    assert config.allow_public_web_research is True

    other_team = Team.objects.create(organization=team.organization, name="Other project")
    assert get_proactive_config(team_id=other_team.id, subscription_id=123).enabled is False


@override_settings(
    PULSE_PROACTIVE_ENABLED=True,
    PULSE_PUBLIC_RESEARCH_ENABLED=False,
    PULSE_ARTIFACT_PREPARATION_ENABLED=True,
)
@pytest.mark.django_db
def test_proactive_configuration_options_only_expose_currently_authorizable_repositories(team, monkeypatch) -> None:
    user_integration_id = uuid4()
    monkeypatch.setattr(
        proactive,
        "list_authorizable_repositories",
        lambda **_kwargs: (
            AuthorizableRepository(
                repository="posthog/posthog",
                github_integration_id=123,
                github_user_integration_id=user_integration_id,
                github_installation_id="456",
            ),
        ),
    )

    options = get_proactive_configuration_options(team_id=team.id, actor_id=456)

    assert options.proactive_available is True
    assert options.public_web_research_available is False
    assert options.draft_pr_available is True
    assert options.repositories == (
        proactive.ProactiveRepositoryOptionDTO(repository="posthog/posthog", repository_integration_id=123),
    )


@pytest.mark.django_db
def test_proactive_history_returns_compact_recommendation_artifact_and_outcome(team) -> None:
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot_hash="a" * 64,
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    recommendation = ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="signup-friction",
        recommendation={
            "title": "Reduce sign-up friction",
            "why_now": "New users are leaving before account setup.",
            "confidence": 0.8,
            "effort": "small",
            "expected_metric_movement": "Increase completed sign-ups.",
        },
        citations=[
            {"title": "Sign-up trend", "url": "https://example.com/sign-up-trend"},
            {"title": "Unsafe", "url": "javascript:alert(1)"},
        ],
    )
    artifact = ProactivePreparedArtifact.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        recommendation=recommendation,
        kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
        status=ProactivePreparedArtifact.Status.ADOPTED,
        artifact_config_hash="b" * 64,
        input_hash="c" * 64,
        url="https://example.com/draft-pr",
        prepared_at=datetime(2026, 9, 8, 9, tzinfo=UTC),
        adopted_at=datetime(2026, 9, 9, 9, tzinfo=UTC),
    )
    ProactiveRecommendationOutcome.objects.for_team(team.id).create(
        team_id=team.id,
        artifact=artifact,
        status=ProactiveRecommendationOutcome.Status.IMPROVED,
        metric_name="Completed sign-ups",
        expected_metric_movement="completed sign-ups",
        direction=ProactiveRecommendationOutcome.Direction.INCREASE,
        baseline_value=Decimal("120"),
        observed_value=Decimal("146.5"),
        delta=Decimal("26.5"),
        baseline_from=date(2026, 9, 1),
        baseline_to=date(2026, 9, 7),
        observed_from=datetime(2026, 9, 9, tzinfo=UTC),
        observed_to=datetime(2026, 9, 15, 23, 59, 59, 999999, tzinfo=UTC),
        due_at=datetime(2026, 9, 16, 9, tzinfo=UTC),
    )

    history = proactive.list_proactive_history(team_id=team.id, subscription_id=123)

    assert len(history) == 1
    entry = history[0]
    assert entry.recommendation_title == "Reduce sign-up friction"
    assert entry.confidence == 0.8
    assert entry.effort == "small"
    assert entry.metric_direction == "increase"
    assert entry.expected_metric_movement == "Increase completed sign-ups."
    assert entry.citations[0].url == "https://example.com/sign-up-trend"
    assert entry.citations[1].url is None
    assert entry.artifact is not None
    assert entry.artifact.status == "adopted"
    assert entry.artifact.adopted_at == artifact.adopted_at
    assert entry.outcome is not None
    assert entry.outcome.direction == "increase"
    assert entry.outcome.expected_metric_movement == "completed sign-ups"
    assert entry.outcome.delta == Decimal("26.5")


@pytest.mark.django_db
def test_one_delivery_claim_reconciles_to_the_same_run(team) -> None:
    delivery_id = uuid4()
    snapshot = {"report": "saved report", "prompt": "look for improvements"}

    first = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=delivery_id, actor_id=456, snapshot=snapshot
    )
    replay = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=delivery_id, actor_id=456, snapshot=snapshot
    )

    assert replay.id == first.id


@pytest.mark.django_db
def test_delivery_replay_rejects_a_different_snapshot(team) -> None:
    delivery_id = uuid4()
    claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=delivery_id, actor_id=456, snapshot={"report": "one"}
    )

    with pytest.raises(ValueError, match="does not match"):
        claim_recommendation_run(
            team_id=team.id,
            subscription_id=123,
            delivery_id=delivery_id,
            actor_id=456,
            snapshot={"report": "two"},
        )


@pytest.mark.django_db
def test_completed_run_replays_the_persisted_appendix(team) -> None:
    run = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=uuid4(), actor_id=456, snapshot={"report": "saved report"}
    )
    result = _result(_recommendation("key", title="Check activation"))

    finalize_recommendation_run(team_id=team.id, run_id=run.id, result=result)
    replay = finalize_recommendation_run(team_id=team.id, run_id=run.id, result=result)

    assert [recommendation.title for recommendation in replay.recommendations] == ["Check activation"]
    assert "measurement" not in ProactiveRecommendation.objects.for_team(team.id).get(run_id=run.id).recommendation


@pytest.mark.django_db
def test_finalization_freezes_persisted_measurement_without_reexecuting_queries(team, monkeypatch) -> None:
    insight = Insight.objects.create(team=team, saved=True, short_id="signup-rate")
    run = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=uuid4(), actor_id=456, snapshot={"report": "saved report"}
    )
    result = _result(
        _recommendation("baseline", measurement_call_id="mcp:insight"),
        completed_mcp_calls=(_measurement_call(insight_id=insight.id, short_id=insight.short_id),),
    )
    monkeypatch.setattr(
        "posthog.api.services.query.process_query_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
    )

    finalize_recommendation_run(team_id=team.id, run_id=run.id, result=result)
    row = ProactiveRecommendation.objects.for_team(team.id).get(run_id=run.id)
    measurement = row.recommendation["measurement"]
    monkeypatch.setattr(proactive, "canonicalize_measurement", lambda **_: (_ for _ in ()).throw(AssertionError()))

    replay = finalize_recommendation_run(team_id=team.id, run_id=run.id, result=result)

    assert measurement["baseline"]["value"] == 0
    assert measurement["source_call_id"] == "mcp:insight"
    assert [item.semantic_key for item in replay.recommendations] == ["baseline"]


@pytest.mark.django_db
def test_unavailable_measurement_still_completes_recommendation_finalization(team) -> None:
    insight = Insight.objects.create(team=team, saved=True, deleted=True, short_id="deleted-rate")
    run = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=uuid4(), actor_id=456, snapshot={"report": "saved report"}
    )

    appendix = finalize_recommendation_run(
        team_id=team.id,
        run_id=run.id,
        result=_result(
            _recommendation("unavailable", measurement_call_id="mcp:insight"),
            completed_mcp_calls=(_measurement_call(insight_id=insight.id, short_id=insight.short_id),),
        ),
    )

    row = ProactiveRecommendation.objects.for_team(team.id).get(run_id=run.id)
    assert appendix.status == "completed"
    assert "measurement" not in row.recommendation


@pytest.mark.django_db
def test_zero_result_and_failure_finalization_are_terminal(team) -> None:
    completed = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=uuid4(), actor_id=456, snapshot={"report": "one"}
    )
    failed = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=uuid4(), actor_id=456, snapshot={"report": "two"}
    )

    empty = finalize_recommendation_run(team_id=team.id, run_id=completed.id, result=_result())
    failure = finalize_recommendation_run(team_id=team.id, run_id=failed.id, failure_code="provider_unavailable")
    replay = finalize_recommendation_run(team_id=team.id, run_id=failed.id, result=_result(_recommendation("late")))

    assert empty.status == "completed"
    assert empty.recommendations == ()
    assert failure.failure_code == "provider_unavailable"
    assert replay.status == "failed"
    assert replay.recommendations == ()


@pytest.mark.django_db
def test_duplicate_keys_are_suppressed_within_and_across_runs(team) -> None:
    first = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=uuid4(), actor_id=456, snapshot={"report": "one"}
    )
    first_appendix = finalize_recommendation_run(
        team_id=team.id,
        run_id=first.id,
        result=_result(_recommendation("same"), _recommendation("same"), _recommendation("first-only")),
    )
    second = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=uuid4(), actor_id=456, snapshot={"report": "two"}
    )
    second_appendix = finalize_recommendation_run(
        team_id=team.id,
        run_id=second.id,
        result=_result(_recommendation("same"), _recommendation("second-only")),
    )

    assert [item.semantic_key for item in first_appendix.recommendations] == ["same", "first-only"]
    assert [item.semantic_key for item in second_appendix.recommendations] == ["second-only"]


@pytest.mark.django_db
def test_duplicate_window_includes_the_exact_ninety_day_boundary(team, monkeypatch) -> None:
    fixed_now = timezone.now()
    first = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=uuid4(), actor_id=456, snapshot={"report": "one"}
    )
    finalize_recommendation_run(team_id=team.id, run_id=first.id, result=_result(_recommendation("boundary")))
    ProactiveRecommendation.objects.for_team(team.id).filter(run_id=first.id).update(
        created_at=fixed_now - timedelta(days=90)
    )
    monkeypatch.setattr(proactive.timezone, "now", lambda: fixed_now)
    second = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=uuid4(), actor_id=456, snapshot={"report": "two"}
    )

    appendix = finalize_recommendation_run(
        team_id=team.id, run_id=second.id, result=_result(_recommendation("boundary"))
    )

    assert appendix.recommendations == ()


@pytest.mark.django_db
def test_same_key_is_allowed_for_another_subscription(team) -> None:
    first = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=uuid4(), actor_id=456, snapshot={"report": "one"}
    )
    finalize_recommendation_run(team_id=team.id, run_id=first.id, result=_result(_recommendation("shared")))
    second = claim_recommendation_run(
        team_id=team.id, subscription_id=999, delivery_id=uuid4(), actor_id=456, snapshot={"report": "two"}
    )

    appendix = finalize_recommendation_run(team_id=team.id, run_id=second.id, result=_result(_recommendation("shared")))

    assert [item.semantic_key for item in appendix.recommendations] == ["shared"]


@pytest.mark.django_db
def test_recent_memory_is_newest_first_and_row_bounded(team, monkeypatch) -> None:
    fixed_now = timezone.now()
    monkeypatch.setattr(proactive.timezone, "now", lambda: fixed_now)
    for index in range(3):
        run = claim_recommendation_run(
            team_id=team.id,
            subscription_id=123,
            delivery_id=uuid4(),
            actor_id=456,
            snapshot={"report": str(index)},
        )
        finalize_recommendation_run(team_id=team.id, run_id=run.id, result=_result(_recommendation(f"key-{index}")))
        ProactiveRecommendation.objects.for_team(team.id).filter(run_id=run.id).update(
            created_at=fixed_now - timedelta(days=index)
        )
    monkeypatch.setattr(proactive, "MAX_MEMORY_ROWS", 2)

    memory = recent_recommendation_memory(team_id=team.id, subscription_id=123)

    assert [item.semantic_key for item in memory] == ["key-0", "key-1"]


@pytest.mark.django_db
def test_recent_memory_byte_cap_counts_the_complete_projection(team, monkeypatch) -> None:
    for key in ("first", "second"):
        run = claim_recommendation_run(
            team_id=team.id,
            subscription_id=123,
            delivery_id=uuid4(),
            actor_id=456,
            snapshot={"report": key},
        )
        finalize_recommendation_run(team_id=team.id, run_id=run.id, result=_result(_recommendation(key)))
    rows = recent_recommendation_memory(team_id=team.id, subscription_id=123)
    newest = rows[0]
    exact_size = len(
        json.dumps(
            {
                "semantic_key": newest.semantic_key,
                "title": newest.title,
                "created_at": newest.created_at,
                "outcome_status": newest.outcome_status,
                "outcome_summary": newest.outcome_summary,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    monkeypatch.setattr(proactive, "MAX_MEMORY_BYTES", exact_size)

    bounded = recent_recommendation_memory(team_id=team.id, subscription_id=123)

    assert bounded == (newest,)


def _memory_recommendation_with_outcome(
    team,
    *,
    semantic_key: str,
    outcome_status: str | None,
    metric_name: str | None = "Activation",
    delta: Decimal | None = Decimal("2"),
) -> None:
    run = claim_recommendation_run(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot={"report": semantic_key},
    )
    finalize_recommendation_run(team_id=team.id, run_id=run.id, result=_result(_recommendation(semantic_key)))
    recommendation = ProactiveRecommendation.objects.for_team(team.id).get(run_id=run.id)
    if outcome_status is None:
        return
    artifact = ProactivePreparedArtifact.objects.for_team(team.id).create(
        team_id=team.id,
        run_id=run.id,
        recommendation=recommendation,
        kind=ProactivePreparedArtifact.Kind.EXPERIMENT_DRAFT,
        status=ProactivePreparedArtifact.Status.ADOPTED,
        artifact_config_hash="a" * 64,
        input_hash="b" * 64,
    )
    ProactiveRecommendationOutcome.objects.for_team(team.id).create(
        team_id=team.id,
        artifact=artifact,
        status=outcome_status,
        metric_name=metric_name,
        delta=delta,
    )


@pytest.mark.django_db
def test_recent_memory_projects_only_safe_outcome_readouts(team) -> None:
    _memory_recommendation_with_outcome(team, semantic_key="none", outcome_status=None)
    _memory_recommendation_with_outcome(
        team, semantic_key="pending", outcome_status=ProactiveRecommendationOutcome.Status.PENDING
    )
    _memory_recommendation_with_outcome(
        team, semantic_key="unavailable", outcome_status=ProactiveRecommendationOutcome.Status.UNAVAILABLE
    )
    _memory_recommendation_with_outcome(
        team, semantic_key="improved", outcome_status=ProactiveRecommendationOutcome.Status.IMPROVED, delta=Decimal("2")
    )
    _memory_recommendation_with_outcome(
        team,
        semantic_key="regressed",
        outcome_status=ProactiveRecommendationOutcome.Status.REGRESSED,
        delta=Decimal("-2"),
    )
    _memory_recommendation_with_outcome(
        team,
        semantic_key="inconclusive",
        outcome_status=ProactiveRecommendationOutcome.Status.INCONCLUSIVE,
        delta=Decimal("0"),
    )

    memory = {item.semantic_key: item for item in recent_recommendation_memory(team_id=team.id, subscription_id=123)}

    assert (memory["none"].outcome_status, memory["none"].outcome_summary) == (None, None)
    assert (memory["pending"].outcome_status, memory["pending"].outcome_summary) == (None, None)
    assert (memory["unavailable"].outcome_status, memory["unavailable"].outcome_summary) == ("unavailable", None)
    assert (memory["improved"].outcome_status, memory["improved"].outcome_summary) == (
        "improved",
        "Metric movement after adoption: Activation increased by 2 (the expected direction).",
    )
    assert (memory["regressed"].outcome_status, memory["regressed"].outcome_summary) == (
        "regressed",
        "Metric movement after adoption: Activation decreased by 2 (the opposite direction).",
    )
    assert (memory["inconclusive"].outcome_status, memory["inconclusive"].outcome_summary) == (
        "inconclusive",
        "Metric movement after adoption: Activation was inconclusive.",
    )


@pytest.mark.django_db
def test_recent_memory_reads_multiple_outcomes_without_per_outcome_queries(team, django_assert_num_queries) -> None:
    _memory_recommendation_with_outcome(
        team, semantic_key="improved", outcome_status=ProactiveRecommendationOutcome.Status.IMPROVED
    )
    _memory_recommendation_with_outcome(
        team, semantic_key="unavailable", outcome_status=ProactiveRecommendationOutcome.Status.UNAVAILABLE
    )

    # The fail-closed manager canonicalizes the raw team ID first; the outcome projection itself is one joined query.
    with django_assert_num_queries(2):
        memory = recent_recommendation_memory(team_id=team.id, subscription_id=123)

    assert {item.outcome_status for item in memory} == {"improved", "unavailable"}


@pytest.mark.django_db
def test_failed_run_is_read_without_restarting(team) -> None:
    delivery_id = uuid4()
    run = claim_recommendation_run(
        team_id=team.id, subscription_id=123, delivery_id=delivery_id, actor_id=456, snapshot={"report": "one"}
    )
    finalize_recommendation_run(team_id=team.id, run_id=run.id, failure_code="timeout")

    appendix = read_recommendation_appendix(team_id=team.id, delivery_id=delivery_id)

    assert appendix is not None
    assert appendix.status == "failed"
    assert appendix.failure_code == "timeout"


@pytest.mark.django_db
def test_generation_persists_and_reuses_its_exact_immutable_handles(team, monkeypatch) -> None:
    delivery_id = uuid4()
    binding = StagedRepositoryBinding(
        repository="posthog/posthog",
        base_sha="a" * 40,
        base_branch="master",
        github_integration_id=123,
        github_user_integration_id=uuid4(),
        github_installation_id="456",
        grant_version="stable-grant",
    )
    generation_input = RecommendationGenerationInput(
        team_id=team.id,
        subscription_id=123,
        delivery_id=delivery_id,
        actor_id=456,
        idempotency_key=f"pulse-recommendations:{delivery_id}",
        report_markdown="saved report",
        prompt="find improvements",
        contexts=(),
        public_web_research=False,
        create_draft_pr=True,
        repository_name="posthog/posthog",
        repository_integration_id=123,
        repository=binding,
    )
    handle = RecommendationGenerationHandle(staged_run_id=uuid4(), task_id=uuid4(), analysis_run_id=uuid4())
    started_inputs: list[RecommendationGenerationInput] = []

    def start(started_input: RecommendationGenerationInput) -> RecommendationGenerationHandle:
        started_inputs.append(started_input)
        return handle

    monkeypatch.setattr(
        proactive,
        "start_recommendation_generation",
        start,
    )
    claimed = claim_recommendation_run(
        team_id=team.id,
        subscription_id=123,
        delivery_id=delivery_id,
        actor_id=456,
        snapshot={"report_hash": "stable"},
    )

    first = proactive.start_or_reuse_recommendation_generation(input=generation_input, run_id=claimed.id)
    replay = proactive.start_or_reuse_recommendation_generation(input=generation_input, run_id=claimed.id)

    run = proactive.ProactiveRecommendationRun.objects.for_team(team.id).get(delivery_id=delivery_id)
    assert first == handle
    assert replay == handle
    assert (run.staged_run_id, run.task_id, run.analysis_run_id) == (
        handle.staged_run_id,
        handle.task_id,
        handle.analysis_run_id,
    )
    assert run.repository_binding == {
        "base_branch": "master",
        "base_sha": "a" * 40,
        "github_installation_id": "456",
        "github_integration_id": 123,
        "github_user_integration_id": str(binding.github_user_integration_id),
        "grant_version": "stable-grant",
        "repository": "posthog/posthog",
    }
    assert run.artifact_config_hash is not None
    assert started_inputs == [generation_input]


@pytest.mark.django_db
def test_pending_generation_reuses_canonical_binding_for_mixed_case_repository_config(team, monkeypatch) -> None:
    delivery_id = uuid4()
    binding = StagedRepositoryBinding(
        repository="posthog/posthog",
        base_sha="a" * 40,
        base_branch="master",
        github_integration_id=123,
        github_user_integration_id=uuid4(),
        github_installation_id="456",
        grant_version="stable-grant",
    )
    generation_input = RecommendationGenerationInput(
        team_id=team.id,
        subscription_id=123,
        delivery_id=delivery_id,
        actor_id=456,
        idempotency_key=f"pulse-recommendations:{delivery_id}",
        report_markdown="saved report",
        prompt="find improvements",
        contexts=(),
        public_web_research=False,
        create_draft_pr=True,
        repository_name="PostHog/posthog",
        repository_integration_id=123,
        repository=binding,
    )
    claimed = claim_recommendation_run(
        team_id=team.id,
        subscription_id=123,
        delivery_id=delivery_id,
        actor_id=456,
        snapshot={"report_hash": "stable"},
    )
    handle = RecommendationGenerationHandle(staged_run_id=uuid4(), task_id=uuid4(), analysis_run_id=uuid4())
    started_inputs: list[RecommendationGenerationInput] = []

    def start(started_input: RecommendationGenerationInput) -> RecommendationGenerationHandle:
        started_inputs.append(started_input)
        return handle

    monkeypatch.setattr(
        proactive,
        "start_recommendation_generation",
        start,
    )

    first = proactive.start_or_reuse_recommendation_generation(input=generation_input, run_id=claimed.id)
    replay = proactive.start_or_reuse_recommendation_generation(input=generation_input, run_id=claimed.id)

    run = proactive.ProactiveRecommendationRun.objects.for_team(team.id).get(id=claimed.id)
    assert run.status == "pending"
    assert first == handle
    assert replay == handle
    assert started_inputs == [generation_input]


@pytest.mark.django_db
def test_repository_consent_is_resolved_through_the_tasks_facade(team, monkeypatch) -> None:
    config = proactive.ProactiveConfigDTO(
        enabled=True,
        allow_public_web_research=True,
        create_draft_pr=True,
        repository="posthog/posthog",
        repository_integration_id=123,
    )
    user_integration_id = uuid4()
    monkeypatch.setattr(
        proactive,
        "list_authorizable_repositories",
        lambda **_kwargs: (
            AuthorizableRepository(
                repository="posthog/posthog",
                github_integration_id=123,
                github_user_integration_id=user_integration_id,
                github_installation_id="456",
            ),
        ),
    )
    monkeypatch.setattr(
        proactive,
        "resolve_staged_repository_binding",
        lambda **_kwargs: ResolvedStagedRepositoryBinding(
            repository="posthog/posthog",
            base_sha="a" * 40,
            base_branch="master",
            github_integration_id=123,
            github_user_integration_id=user_integration_id,
            github_installation_id="456",
            grant_version="stable-grant",
        ),
    )

    binding = proactive.resolve_draft_repository_binding(team_id=team.id, actor_id=456, config=config)

    assert binding == StagedRepositoryBinding(
        repository="posthog/posthog",
        base_sha="a" * 40,
        base_branch="master",
        github_integration_id=123,
        github_user_integration_id=user_integration_id,
        github_installation_id="456",
        grant_version="stable-grant",
    )


@pytest.mark.django_db
def test_missing_repository_consent_degrades_to_no_repository(team, monkeypatch) -> None:
    config = proactive.ProactiveConfigDTO(
        enabled=True,
        allow_public_web_research=True,
        create_draft_pr=True,
        repository="posthog/posthog",
        repository_integration_id=None,
    )
    monkeypatch.setattr(proactive, "list_authorizable_repositories", lambda **_kwargs: ())

    assert proactive.resolve_draft_repository_binding(team_id=team.id, actor_id=456, config=config) is None
