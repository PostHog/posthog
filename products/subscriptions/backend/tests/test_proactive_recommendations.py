import json
from datetime import timedelta
from uuid import uuid4

import pytest

from django.apps import apps
from django.utils import timezone

from posthog.models import Team

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
    read_recommendation_appendix,
    recent_recommendation_memory,
)
from products.subscriptions.backend.models import ProactiveRecommendation
from products.tasks.backend.facade.repository_authorization import (
    AuthorizableRepository,
    ResolvedStagedRepositoryBinding,
)
from products.tasks.backend.facade.staged_execution import StagedRepositoryBinding


def _recommendation(semantic_key: str, *, title: str | None = None) -> Recommendation:
    return Recommendation(
        kind="investigation",
        title=title or f"Check {semantic_key}",
        rationale="Activation fell",
        target="activation",
        why_now="This week",
        confidence=0.8,
        effort="small",
        metric_name="activation rate",
        metric_direction="increase",
        expected_metric_movement="5%",
        citation_ids=("report",),
        semantic_key=semantic_key,
    )


def _result(*recommendations: Recommendation) -> RecommendationResult:
    return RecommendationResult(
        recommendations=recommendations,
        citations=(RecommendationCitation(id="report", title="Subscription report"),),
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
            {"semantic_key": newest.semantic_key, "title": newest.title, "created_at": newest.created_at},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    monkeypatch.setattr(proactive, "MAX_MEMORY_BYTES", exact_size)

    bounded = recent_recommendation_memory(team_id=team.id, subscription_id=123)

    assert bounded == (newest,)


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
