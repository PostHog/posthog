from __future__ import annotations

from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

import pytest_asyncio

from posthog.sync import database_sync_to_async

from products.signals.backend.agent_harness.tools import (
    DEFAULT_MEMORY_TTL_DAYS,
    MAX_EVIDENCE_ENTRIES,
    MAX_MEMORY_TTL_DAYS,
    EvidenceEntry,
    HumanConfirmedMemoryError,
    InvalidEmitError,
    InvalidMemoryError,
    emit_finding,
    forget,
    get_run,
    remember,
    search_memory,
    search_recent_runs,
)
from products.signals.backend.agent_harness.tools.emit import (
    SOURCE_PRODUCT,
    SOURCE_TYPE,
    _build_extra,
    _mark_finding_emitted,
    _record_finding_pre_emit,
    _validate_inputs,
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


# --- emit adapter tests --- (Phase 3c)


class TestValidateEmitInputs:
    """Pure validation — no DB."""

    def test_empty_description_raises(self) -> None:
        with pytest.raises(InvalidEmitError, match="description"):
            _validate_inputs("", 0.5, 0.5, [])

    def test_whitespace_only_description_raises(self) -> None:
        with pytest.raises(InvalidEmitError, match="description"):
            _validate_inputs("   \n\t", 0.5, 0.5, [])

    @pytest.mark.parametrize("weight", [-0.1, 1.1, 2.0])
    def test_weight_out_of_range_raises(self, weight: float) -> None:
        with pytest.raises(InvalidEmitError, match="weight"):
            _validate_inputs("ok", weight, 0.5, [])

    @pytest.mark.parametrize("confidence", [-0.1, 1.1])
    def test_confidence_out_of_range_raises(self, confidence: float) -> None:
        with pytest.raises(InvalidEmitError, match="confidence"):
            _validate_inputs("ok", 0.5, confidence, [])

    def test_too_many_evidence_entries_raises(self) -> None:
        # +1 over the cap so the boundary is exact.
        many = [EvidenceEntry(source_product="logs", summary=f"e{i}") for i in range(MAX_EVIDENCE_ENTRIES + 1)]
        with pytest.raises(InvalidEmitError, match="evidence"):
            _validate_inputs("ok", 0.5, 0.5, many)

    def test_at_capacity_evidence_passes(self) -> None:
        many = [EvidenceEntry(source_product="logs", summary=f"e{i}") for i in range(MAX_EVIDENCE_ENTRIES)]
        # Should not raise.
        _validate_inputs("ok", 0.5, 0.5, many)


class TestBuildEmitExtra:
    """Pure shaping — no DB. Asserts the dict matches what `SignalsAgentSignalExtra` expects."""

    def _minimal(self) -> dict:
        return _build_extra(
            run_id="run-uuid",
            finding_id="finding-uuid",
            skill_name="signals-agent-errors",
            skill_version=2,
            confidence=0.7,
            evidence=[EvidenceEntry(source_product="error_tracking", summary="500s on /checkout")],
            hypothesis=None,
            severity=None,
            dedupe_keys=None,
            time_range=None,
            mcp_trace_id=None,
        )

    def test_minimal_extra_has_only_required_fields(self) -> None:
        extra = self._minimal()
        # Required by schema:
        assert extra["agent_run_id"] == "run-uuid"
        assert extra["finding_id"] == "finding-uuid"
        assert extra["skill_name"] == "signals-agent-errors"
        assert extra["confidence"] == 0.7
        assert extra["evidence"] == [
            {"source_product": "error_tracking", "summary": "500s on /checkout", "entity_id": None}
        ]
        # Optional fields omitted, not None — pydantic with extra="forbid" tolerates absence
        # but rejects unexpected keys, so omission is the right shape.
        for opt in ("hypothesis", "severity", "dedupe_keys", "time_range", "mcp_trace_id"):
            assert opt not in extra

    def test_skill_version_cast_to_float(self) -> None:
        extra = self._minimal()
        # SignalsAgentSignalExtra.skill_version is float in posthog/schema.py.
        assert isinstance(extra["skill_version"], float)
        assert extra["skill_version"] == 2.0

    def test_full_extra_includes_all_optional_fields(self) -> None:
        extra = _build_extra(
            run_id="run-uuid",
            finding_id="finding-uuid",
            skill_name="signals-agent-errors",
            skill_version=1,
            confidence=0.9,
            evidence=[EvidenceEntry(source_product="logs", summary="bursts of 500s", entity_id="log-1")],
            hypothesis="checkout post-deploy regression",
            severity="P1",
            dedupe_keys=["checkout-500-spike"],
            time_range=("2026-04-29T00:00:00Z", "2026-04-30T00:00:00Z"),
            mcp_trace_id="trace-abc",
        )
        assert extra["hypothesis"] == "checkout post-deploy regression"
        assert extra["severity"] == "P1"
        assert extra["dedupe_keys"] == ["checkout-500-spike"]
        assert extra["time_range"] == {"date_from": "2026-04-29T00:00:00Z", "date_to": "2026-04-30T00:00:00Z"}
        assert extra["mcp_trace_id"] == "trace-abc"

    def test_built_extra_validates_against_schema_variant(self) -> None:
        """Round-trip: the extra we build must pass `SignalsAgentSignalInput` validation
        — this is the contract `emit_signal` checks via `_SIGNAL_VARIANT_LOOKUP`."""
        from posthog.schema import SignalsAgentSignalInput

        extra = self._minimal()
        # The full top-level signal — same shape `_SIGNAL_VARIANT_LOOKUP` validates.
        SignalsAgentSignalInput.model_validate(
            {
                "source_product": SOURCE_PRODUCT,
                "source_type": SOURCE_TYPE,
                "source_id": "run:run-uuid:finding:finding-uuid",
                "description": "d",
                "weight": 0.5,
                "extra": extra,
            }
        )


class TestRecordFindingPreEmit(BaseTest):
    def test_inserts_new_finding_with_emitted_false(self) -> None:
        run = _create_run(self.team, findings=[])

        already = _record_finding_pre_emit(
            run_id=str(run.id),
            finding_id="f-new",
            description="d",
            weight=0.5,
            extra={"agent_run_id": str(run.id), "finding_id": "f-new"},
        )

        assert already is False
        run.refresh_from_db()
        assert len(run.findings) == 1
        entry = run.findings[0]
        assert entry["finding_id"] == "f-new"
        assert entry["emitted"] is False
        assert "first_attempt_at" in entry
        assert "last_attempt_at" in entry
        assert "emitted_at" not in entry

    def test_overwrites_unemitted_finding_on_retry(self) -> None:
        run = _create_run(
            self.team,
            findings=[
                {
                    "finding_id": "f-retry",
                    "description": "first",
                    "weight": 0.3,
                    "extra": {},
                    "emitted": False,
                    "first_attempt_at": "2026-04-29T10:00:00+00:00",
                    "last_attempt_at": "2026-04-29T10:00:00+00:00",
                }
            ],
        )

        already = _record_finding_pre_emit(
            run_id=str(run.id),
            finding_id="f-retry",
            description="second",
            weight=0.7,
            extra={"agent_run_id": str(run.id), "finding_id": "f-retry"},
        )

        assert already is False
        run.refresh_from_db()
        assert len(run.findings) == 1
        entry = run.findings[0]
        assert entry["description"] == "second"
        assert entry["weight"] == 0.7
        # Original first_attempt_at preserved; last_attempt_at refreshed.
        assert entry["first_attempt_at"] == "2026-04-29T10:00:00+00:00"
        assert entry["last_attempt_at"] != "2026-04-29T10:00:00+00:00"

    def test_returns_true_when_already_emitted(self) -> None:
        run = _create_run(
            self.team,
            findings=[
                {
                    "finding_id": "f-done",
                    "description": "already done",
                    "weight": 0.5,
                    "extra": {},
                    "emitted": True,
                    "first_attempt_at": "2026-04-29T10:00:00+00:00",
                    "last_attempt_at": "2026-04-29T10:00:00+00:00",
                    "emitted_at": "2026-04-29T10:00:01+00:00",
                }
            ],
        )

        already = _record_finding_pre_emit(
            run_id=str(run.id),
            finding_id="f-done",
            description="changed",
            weight=0.99,
            extra={"agent_run_id": str(run.id), "finding_id": "f-done"},
        )

        assert already is True
        run.refresh_from_db()
        # The emitted entry is left untouched (no overwrite of a successful emit).
        assert run.findings[0]["description"] == "already done"
        assert run.findings[0]["weight"] == 0.5


class TestMarkFindingEmitted(BaseTest):
    def test_marks_finding_with_emitted_at_timestamp(self) -> None:
        run = _create_run(
            self.team,
            findings=[
                {
                    "finding_id": "f-1",
                    "description": "d",
                    "weight": 0.5,
                    "extra": {},
                    "emitted": False,
                    "first_attempt_at": "2026-04-29T10:00:00+00:00",
                    "last_attempt_at": "2026-04-29T10:00:00+00:00",
                }
            ],
        )

        _mark_finding_emitted(run_id=str(run.id), finding_id="f-1")

        run.refresh_from_db()
        entry = run.findings[0]
        assert entry["emitted"] is True
        assert "emitted_at" in entry

    def test_no_op_for_unknown_finding_id(self) -> None:
        run = _create_run(
            self.team,
            findings=[
                {
                    "finding_id": "f-1",
                    "description": "d",
                    "weight": 0.5,
                    "extra": {},
                    "emitted": False,
                }
            ],
        )

        # Should not raise.
        _mark_finding_emitted(run_id=str(run.id), finding_id="nope")

        run.refresh_from_db()
        assert run.findings[0]["emitted"] is False


# --- emit_finding async tests ---


@pytest_asyncio.fixture
async def aorganization_emit():
    from posthog.models import Organization

    org = await database_sync_to_async(Organization.objects.create)(
        name="signals-agent-emit", is_ai_data_processing_approved=True
    )
    return org


@pytest_asyncio.fixture
async def ateam_emit(aorganization_emit):
    from posthog.models import Team

    from products.signals.backend.models import SignalSourceConfig

    team = await database_sync_to_async(Team.objects.create)(organization=aorganization_emit, name="emit-team")
    # The signals_agent source must be explicitly enabled per-team — emit_signal()
    # silently no-ops without it, and the harness preflight mirrors that gate.
    # Default to enabled in tests so the existing happy-path / failure-path emit
    # tests stay focused on what they actually exercise. Tests that exercise the
    # gates themselves create their own SignalSourceConfig overrides.
    await database_sync_to_async(SignalSourceConfig.objects.create)(
        team=team,
        source_product="signals_agent",
        source_type="cross_source_issue",
        enabled=True,
    )
    return team


@pytest_asyncio.fixture
async def arun_emit(ateam_emit):
    run = await database_sync_to_async(SignalAgentRun.objects.create)(
        team=ateam_emit,
        skill_name="signals-agent-errors",
        skill_version=3,
        status=SignalAgentRun.Status.RUNNING,
    )
    return run


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_happy_path_calls_emit_signal_and_marks_emitted(ateam_emit, arun_emit):
    evidence = [EvidenceEntry(source_product="error_tracking", summary="500s spike on /checkout")]

    with patch("products.signals.backend.api.emit_signal", new=AsyncMock()) as mock_emit:
        result = await emit_finding(
            team=ateam_emit,
            run=arun_emit,
            description="Checkout 500s post-deploy",
            weight=0.7,
            confidence=0.85,
            evidence=evidence,
            hypothesis="post-deploy regression",
            finding_id="f-happy",
        )

    assert result.emitted is True
    assert result.skipped_reason is None
    assert result.finding_id == "f-happy"
    mock_emit.assert_awaited_once()
    call_kwargs = mock_emit.await_args.kwargs
    assert call_kwargs["team"] is ateam_emit
    assert call_kwargs["source_product"] == SOURCE_PRODUCT
    assert call_kwargs["source_type"] == SOURCE_TYPE
    assert call_kwargs["source_id"] == f"run:{arun_emit.id}:finding:f-happy"
    assert call_kwargs["description"] == "Checkout 500s post-deploy"
    assert call_kwargs["weight"] == 0.7
    assert call_kwargs["extra"]["agent_run_id"] == str(arun_emit.id)
    assert call_kwargs["extra"]["finding_id"] == "f-happy"
    assert call_kwargs["extra"]["skill_name"] == "signals-agent-errors"
    assert call_kwargs["extra"]["skill_version"] == 3.0

    refreshed = await database_sync_to_async(SignalAgentRun.objects.get)(id=arun_emit.id)
    assert len(refreshed.findings) == 1
    assert refreshed.findings[0]["emitted"] is True
    assert "emitted_at" in refreshed.findings[0]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_shadow_mode_skips_external_emit(ateam_emit, arun_emit):
    with patch("products.signals.backend.api.emit_signal", new=AsyncMock()) as mock_emit:
        result = await emit_finding(
            team=ateam_emit,
            run=arun_emit,
            description="d",
            weight=0.5,
            confidence=0.5,
            evidence=[EvidenceEntry(source_product="logs", summary="x")],
            shadow_mode=True,
            finding_id="f-shadow",
        )

    assert result.emitted is False
    assert result.skipped_reason == "shadow_mode"
    mock_emit.assert_not_awaited()
    refreshed = await database_sync_to_async(SignalAgentRun.objects.get)(id=arun_emit.id)
    assert refreshed.findings[0]["emitted"] is False


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_idempotent_on_repeat_finding_id(ateam_emit, arun_emit):
    evidence = [EvidenceEntry(source_product="logs", summary="x")]

    with patch("products.signals.backend.api.emit_signal", new=AsyncMock()) as mock_emit:
        first = await emit_finding(
            team=ateam_emit,
            run=arun_emit,
            description="d",
            weight=0.5,
            confidence=0.5,
            evidence=evidence,
            finding_id="f-dup",
        )
        second = await emit_finding(
            team=ateam_emit,
            run=arun_emit,
            description="d",
            weight=0.5,
            confidence=0.5,
            evidence=evidence,
            finding_id="f-dup",
        )

    assert first.skipped_reason is None
    assert second.emitted is True
    assert second.skipped_reason == "already_emitted"
    # External emit fired exactly once across both calls.
    assert mock_emit.await_count == 1


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_validation_error_does_not_persist_or_emit(ateam_emit, arun_emit):
    with patch("products.signals.backend.api.emit_signal", new=AsyncMock()) as mock_emit:
        with pytest.raises(InvalidEmitError):
            await emit_finding(
                team=ateam_emit,
                run=arun_emit,
                description="",  # empty -> validation error
                weight=0.5,
                confidence=0.5,
                evidence=[EvidenceEntry(source_product="logs", summary="x")],
            )

    mock_emit.assert_not_awaited()
    refreshed = await database_sync_to_async(SignalAgentRun.objects.get)(id=arun_emit.id)
    assert refreshed.findings == []


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_emit_signal_raises_leaves_finding_unemitted(ateam_emit, arun_emit):
    boom = AsyncMock(side_effect=RuntimeError("temporal exploded"))
    with patch("products.signals.backend.api.emit_signal", new=boom):
        with pytest.raises(RuntimeError, match="temporal"):
            await emit_finding(
                team=ateam_emit,
                run=arun_emit,
                description="d",
                weight=0.5,
                confidence=0.5,
                evidence=[EvidenceEntry(source_product="logs", summary="x")],
                finding_id="f-fails",
            )

    refreshed = await database_sync_to_async(SignalAgentRun.objects.get)(id=arun_emit.id)
    assert len(refreshed.findings) == 1
    # Pre-emit row recorded but NOT marked emitted, so a later run can spot the gap.
    assert refreshed.findings[0]["finding_id"] == "f-fails"
    assert refreshed.findings[0]["emitted"] is False


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_auto_generates_finding_id_when_not_provided(ateam_emit, arun_emit):
    with patch("products.signals.backend.api.emit_signal", new=AsyncMock()):
        result = await emit_finding(
            team=ateam_emit,
            run=arun_emit,
            description="d",
            weight=0.5,
            confidence=0.5,
            evidence=[EvidenceEntry(source_product="logs", summary="x")],
        )

    # Returned finding_id is a uuid string.
    import uuid

    uuid.UUID(result.finding_id)  # raises ValueError if not a valid uuid


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_returns_skipped_when_ai_processing_not_approved(arun_emit, ateam_emit):
    # Flip the org gate that emit_signal() checks. Without the harness preflight, the
    # emit_signal call would silently no-op and we'd report emitted=True; with the
    # preflight, we surface the truth on the run row.
    org = await database_sync_to_async(lambda: ateam_emit.organization)()
    org.is_ai_data_processing_approved = False
    await database_sync_to_async(org.save)()

    with patch("products.signals.backend.api.emit_signal", new=AsyncMock()) as mock_emit:
        result = await emit_finding(
            team=ateam_emit,
            run=arun_emit,
            description="d",
            weight=0.5,
            confidence=0.5,
            evidence=[EvidenceEntry(source_product="logs", summary="x")],
            finding_id="f-not-approved",
        )

    assert result.emitted is False
    assert result.skipped_reason == "ai_processing_not_approved"
    mock_emit.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_returns_skipped_when_source_disabled(arun_emit, ateam_emit):
    # Fixture seeds an enabled config; flip it off to exercise the gate.
    from products.signals.backend.models import SignalSourceConfig

    await database_sync_to_async(
        SignalSourceConfig.objects.filter(
            team=ateam_emit, source_product=SOURCE_PRODUCT, source_type=SOURCE_TYPE
        ).update
    )(enabled=False)

    with patch("products.signals.backend.api.emit_signal", new=AsyncMock()) as mock_emit:
        result = await emit_finding(
            team=ateam_emit,
            run=arun_emit,
            description="d",
            weight=0.5,
            confidence=0.5,
            evidence=[EvidenceEntry(source_product="logs", summary="x")],
            finding_id="f-source-off",
        )

    assert result.emitted is False
    assert result.skipped_reason == "source_disabled"
    mock_emit.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_shadow_mode_short_circuits_before_preflight(arun_emit, ateam_emit):
    # Shadow_mode wins over preflight: the agent's intent is "don't fire externally,
    # just persist", which we honor regardless of org/source gates so shadow runs
    # produce predictable observability data even on misconfigured teams.
    org = await database_sync_to_async(lambda: ateam_emit.organization)()
    org.is_ai_data_processing_approved = False
    await database_sync_to_async(org.save)()

    with patch("products.signals.backend.api.emit_signal", new=AsyncMock()) as mock_emit:
        result = await emit_finding(
            team=ateam_emit,
            run=arun_emit,
            description="d",
            weight=0.5,
            confidence=0.5,
            evidence=[EvidenceEntry(source_product="logs", summary="x")],
            shadow_mode=True,
            finding_id="f-shadow-vs-preflight",
        )

    assert result.emitted is False
    assert result.skipped_reason == "shadow_mode"
    mock_emit.assert_not_called()
