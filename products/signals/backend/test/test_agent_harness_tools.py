from __future__ import annotations

from datetime import timedelta

import pytest
from posthog.test.base import BaseTest

from django.utils import timezone

from products.signals.backend.agent_harness.tools import (
    DEFAULT_MEMORY_TTL_DAYS,
    MAX_MEMORY_TTL_DAYS,
    HumanConfirmedMemoryError,
    InvalidMemoryError,
    forget,
    get_run,
    remember,
    search_memory,
    search_recent_runs,
)
from products.signals.backend.agent_harness.tools.memory import MAX_MEMORY_SEARCH_LIMIT
from products.signals.backend.agent_harness.tools.runs import MAX_RUN_SEARCH_LIMIT
from products.signals.backend.models import SignalAgentRun, SignalMemory


def _create_run(team, **overrides) -> SignalAgentRun:
    defaults: dict = {
        "skill_name": "signals-agent-errors",
        "skill_version": 1,
        "status": SignalAgentRun.Status.COMPLETED,
        "summary": "found a checkout 500 spike on /api/checkout",
        "findings": [{"id": "f1"}],
    }
    defaults.update(overrides)
    return SignalAgentRun.objects.create(team=team, **defaults)


class TestSearchRecentRuns(BaseTest):
    def test_returns_runs_for_team_in_reverse_chronological_order(self) -> None:
        first = _create_run(self.team, summary="older finding")
        second = _create_run(self.team, summary="newer finding")
        # Force ordering by tweaking started_at because auto_now_add resolution can collide.
        SignalAgentRun.objects.filter(id=first.id).update(started_at=timezone.now() - timedelta(hours=2))
        SignalAgentRun.objects.filter(id=second.id).update(started_at=timezone.now() - timedelta(hours=1))

        results = search_recent_runs(team_id=self.team.id)

        assert [r.run_id for r in results] == [str(second.id), str(first.id)]

    def test_filters_by_text_via_ilike(self) -> None:
        _create_run(self.team, summary="checkout funnel got worse")
        _create_run(self.team, summary="image-load p99 spiked")

        hits = search_recent_runs(team_id=self.team.id, text="checkout")

        assert len(hits) == 1
        assert "checkout" in hits[0].summary

    def test_filters_by_since(self) -> None:
        old = _create_run(self.team, summary="ancient")
        recent = _create_run(self.team, summary="fresh")
        SignalAgentRun.objects.filter(id=old.id).update(started_at=timezone.now() - timedelta(days=10))
        SignalAgentRun.objects.filter(id=recent.id).update(started_at=timezone.now() - timedelta(hours=1))

        hits = search_recent_runs(team_id=self.team.id, since=timezone.now() - timedelta(days=1))

        assert [r.run_id for r in hits] == [str(recent.id)]

    def test_does_not_leak_runs_from_other_teams(self) -> None:
        # `BaseTest` only seeds one team. Create a sibling team in the same org for isolation.
        from posthog.models import Team

        other = Team.objects.create(organization=self.organization, name="other")
        _create_run(self.team, summary="mine")
        _create_run(other, summary="not mine")

        hits = search_recent_runs(team_id=self.team.id)

        assert all(r.summary == "mine" for r in hits)

    def test_limit_clamped_to_max(self) -> None:
        for i in range(MAX_RUN_SEARCH_LIMIT + 5):
            _create_run(self.team, summary=f"r{i}")

        hits = search_recent_runs(team_id=self.team.id, limit=MAX_RUN_SEARCH_LIMIT + 50)

        assert len(hits) == MAX_RUN_SEARCH_LIMIT

    def test_findings_count_reflects_findings_array_length(self) -> None:
        _create_run(self.team, findings=[{"id": "a"}, {"id": "b"}, {"id": "c"}])

        hits = search_recent_runs(team_id=self.team.id, limit=1)

        assert hits[0].findings_count == 3


class TestGetRun(BaseTest):
    def test_returns_full_run_payload(self) -> None:
        run = _create_run(
            self.team,
            findings=[{"id": "f1"}],
            hypotheses_considered=[{"text": "thought about it"}],
            tool_call_log=[{"tool": "search_memory"}],
            budget_used={"runtime_s": 3.2},
            metadata={"skill_id": "abc"},
        )

        detail = get_run(team_id=self.team.id, run_id=str(run.id))

        assert detail is not None
        assert detail.run_id == str(run.id)
        assert detail.findings == [{"id": "f1"}]
        assert detail.hypotheses_considered == [{"text": "thought about it"}]
        assert detail.tool_call_log == [{"tool": "search_memory"}]
        assert detail.budget_used == {"runtime_s": 3.2}
        assert detail.metadata == {"skill_id": "abc"}

    def test_returns_none_for_unknown_id(self) -> None:
        detail = get_run(team_id=self.team.id, run_id="00000000-0000-0000-0000-000000000000")
        assert detail is None

    def test_does_not_leak_run_from_another_team(self) -> None:
        from posthog.models import Team

        other = Team.objects.create(organization=self.organization, name="other-team")
        run = _create_run(other)

        detail = get_run(team_id=self.team.id, run_id=str(run.id))

        assert detail is None  # team scoping enforced even when caller knows the UUID


class TestRemember(BaseTest):
    def test_creates_agent_inference_entry_with_default_ttl(self) -> None:
        before = timezone.now()
        entry = remember(team_id=self.team.id, key="known-noise", content="ignore /favicon 404s")

        row = SignalMemory.objects.get(team_id=self.team.id, key="known-noise")
        assert row.authority == SignalMemory.Authority.AGENT_INFERENCE
        assert row.content == "ignore /favicon 404s"
        assert row.expires_at is not None
        elapsed = (row.expires_at - before).total_seconds()
        # Default 7-day TTL: allow ±10s of slack for query execution.
        assert abs(elapsed - timedelta(days=DEFAULT_MEMORY_TTL_DAYS).total_seconds()) < 10
        assert entry.key == "known-noise"
        assert entry.authority == SignalMemory.Authority.AGENT_INFERENCE

    def test_idempotent_upsert_on_team_key(self) -> None:
        first = remember(team_id=self.team.id, key="k", content="v1")
        second = remember(team_id=self.team.id, key="k", content="v2", tags=["new"])

        assert first.key == second.key
        rows = SignalMemory.objects.filter(team_id=self.team.id, key="k")
        assert rows.count() == 1
        assert rows.first().content == "v2"
        assert rows.first().tags == ["new"]

    def test_clamps_ttl_to_max(self) -> None:
        before = timezone.now()
        remember(team_id=self.team.id, key="k", content="v", ttl_days=MAX_MEMORY_TTL_DAYS + 1000)

        row = SignalMemory.objects.get(team_id=self.team.id, key="k")
        assert (row.expires_at - before).days >= MAX_MEMORY_TTL_DAYS - 1
        assert (row.expires_at - before).days <= MAX_MEMORY_TTL_DAYS + 1

    def test_rejects_overwrite_of_human_confirmed(self) -> None:
        # Human-authored row, never expires.
        SignalMemory.objects.create(
            team=self.team,
            key="locked",
            content="human said so",
            authority=SignalMemory.Authority.HUMAN_CONFIRMED,
        )

        with pytest.raises(HumanConfirmedMemoryError):
            remember(team_id=self.team.id, key="locked", content="agent override")

        row = SignalMemory.objects.get(team_id=self.team.id, key="locked")
        assert row.content == "human said so"
        assert row.authority == SignalMemory.Authority.HUMAN_CONFIRMED

    def test_rejects_empty_key_or_content(self) -> None:
        with pytest.raises(InvalidMemoryError):
            remember(team_id=self.team.id, key="", content="x")
        with pytest.raises(InvalidMemoryError):
            remember(team_id=self.team.id, key="   ", content="x")
        with pytest.raises(InvalidMemoryError):
            remember(team_id=self.team.id, key="k", content="")

    def test_links_to_creating_run(self) -> None:
        run = _create_run(self.team)
        entry = remember(
            team_id=self.team.id,
            key="lineage",
            content="x",
            run_id=str(run.id),
        )
        assert entry.created_by_run_id == str(run.id)


class TestForget(BaseTest):
    def test_deletes_agent_inference_entry(self) -> None:
        remember(team_id=self.team.id, key="k", content="v")

        result = forget(team_id=self.team.id, key="k")

        assert result is True
        assert not SignalMemory.objects.filter(team_id=self.team.id, key="k").exists()

    def test_returns_false_when_key_missing(self) -> None:
        assert forget(team_id=self.team.id, key="never-existed") is False

    def test_refuses_to_delete_human_confirmed(self) -> None:
        SignalMemory.objects.create(
            team=self.team,
            key="locked",
            content="human said so",
            authority=SignalMemory.Authority.HUMAN_CONFIRMED,
        )

        with pytest.raises(HumanConfirmedMemoryError):
            forget(team_id=self.team.id, key="locked")

        assert SignalMemory.objects.filter(team_id=self.team.id, key="locked").exists()


class TestSearchMemory(BaseTest):
    def test_returns_only_unexpired_by_default(self) -> None:
        SignalMemory.objects.create(
            team=self.team,
            key="active",
            content="active",
            authority=SignalMemory.Authority.AGENT_INFERENCE,
            expires_at=timezone.now() + timedelta(days=1),
        )
        SignalMemory.objects.create(
            team=self.team,
            key="expired",
            content="expired",
            authority=SignalMemory.Authority.AGENT_INFERENCE,
            expires_at=timezone.now() - timedelta(days=1),
        )

        results = search_memory(team_id=self.team.id)

        keys = {e.key for e in results}
        assert "active" in keys
        assert "expired" not in keys

    def test_include_expired_surfaces_them(self) -> None:
        SignalMemory.objects.create(
            team=self.team,
            key="expired",
            content="expired",
            authority=SignalMemory.Authority.AGENT_INFERENCE,
            expires_at=timezone.now() - timedelta(days=1),
        )

        results = search_memory(team_id=self.team.id, include_expired=True)

        assert any(e.key == "expired" for e in results)

    def test_human_confirmed_with_no_expiry_visible(self) -> None:
        SignalMemory.objects.create(
            team=self.team,
            key="forever",
            content="permanent",
            authority=SignalMemory.Authority.HUMAN_CONFIRMED,
            expires_at=None,
        )

        results = search_memory(team_id=self.team.id)

        assert any(e.key == "forever" and e.authority == SignalMemory.Authority.HUMAN_CONFIRMED for e in results)

    def test_text_filter_uses_ilike(self) -> None:
        remember(team_id=self.team.id, key="k1", content="The CHECKOUT funnel is broken")
        remember(team_id=self.team.id, key="k2", content="Image loading is slow")

        results = search_memory(team_id=self.team.id, text="checkout")

        assert len(results) == 1
        assert results[0].key == "k1"

    def test_tags_filter_uses_array_overlap(self) -> None:
        remember(team_id=self.team.id, key="k1", content="x", tags=["errors", "checkout"])
        remember(team_id=self.team.id, key="k2", content="y", tags=["llm"])
        remember(team_id=self.team.id, key="k3", content="z", tags=["replay", "errors"])

        results = search_memory(team_id=self.team.id, tags=["errors"])

        keys = {e.key for e in results}
        assert keys == {"k1", "k3"}

    def test_does_not_leak_memories_from_other_teams(self) -> None:
        from posthog.models import Team

        other = Team.objects.create(organization=self.organization, name="other-team")
        remember(team_id=self.team.id, key="mine", content="mine")
        remember(team_id=other.id, key="theirs", content="theirs")

        results = search_memory(team_id=self.team.id)

        assert all(e.key == "mine" for e in results)

    def test_limit_clamped_to_max(self) -> None:
        for i in range(MAX_MEMORY_SEARCH_LIMIT + 5):
            remember(team_id=self.team.id, key=f"k{i:03d}", content=f"c{i}")

        results = search_memory(team_id=self.team.id, limit=MAX_MEMORY_SEARCH_LIMIT + 50)

        assert len(results) == MAX_MEMORY_SEARCH_LIMIT
