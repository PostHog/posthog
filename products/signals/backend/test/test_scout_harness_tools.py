from __future__ import annotations

from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

import pytest_asyncio

from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun, SignalScratchpad
from products.signals.backend.scout_harness.tools import (
    MAX_EVIDENCE_ENTRIES,
    EvidenceEntry,
    InvalidEmitError,
    InvalidScratchpadError,
    emit_finding,
    forget,
    get_run,
    remember,
    search_recent_runs,
    search_scratchpad,
)
from products.signals.backend.scout_harness.tools.emit import (
    SOURCE_PRODUCT,
    SOURCE_TYPE,
    _build_extra,
    _validate_inputs,
    emit_finding_sync,
)
from products.signals.backend.scout_harness.tools.runs import MAX_RUN_SEARCH_LIMIT
from products.signals.backend.scout_harness.tools.scratchpad import (
    MAX_SCRATCHPAD_CONTENT_LENGTH,
    MAX_SCRATCHPAD_SEARCH_LIMIT,
)
from products.tasks.backend.models import Task, TaskRun


def _make_task_run(team, *, status: str | None = None) -> TaskRun:
    task = Task.objects.create(
        team=team,
        title="scout run",
        description="scout run",
        origin_product=Task.OriginProduct.SIGNALS_SCOUT,
    )
    task_run = TaskRun.objects.create(task=task, team=team)
    if status is not None:
        TaskRun.objects.filter(id=task_run.id).update(status=status)
        task_run.refresh_from_db()
    return task_run


def _create_run(team, **overrides) -> SignalScoutRun:
    """Build a SignalScoutRun bridge row with a backing TaskRun.

    Default TaskRun status is COMPLETED so summary/detail surface a terminal
    state — tests that need IN_PROGRESS pass `task_run_status` explicitly.
    """
    task_run_status = overrides.pop("task_run_status", TaskRun.Status.COMPLETED)
    task_run = _make_task_run(team, status=task_run_status)
    defaults: dict = {
        "task_run": task_run,
        "skill_name": "signals-scout-errors",
        "skill_version": 1,
    }
    defaults.update(overrides)
    return SignalScoutRun.objects.create(team=team, **defaults)


class TestSearchRecentRuns(BaseTest):
    def test_returns_runs_for_team_in_reverse_chronological_order(self) -> None:
        first = _create_run(self.team)
        second = _create_run(self.team)
        # Force ordering by tweaking the bridge `created_at` (auto_now_add can collide).
        SignalScoutRun.objects.filter(id=first.id).update(created_at=timezone.now() - timedelta(hours=2))
        SignalScoutRun.objects.filter(id=second.id).update(created_at=timezone.now() - timedelta(hours=1))

        results = search_recent_runs(team_id=self.team.id)

        assert [r.run_id for r in results] == [str(second.id), str(first.id)]

    def test_filters_by_date_from(self) -> None:
        old = _create_run(self.team)
        recent = _create_run(self.team)
        SignalScoutRun.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=10))
        SignalScoutRun.objects.filter(id=recent.id).update(created_at=timezone.now() - timedelta(hours=1))

        hits = search_recent_runs(team_id=self.team.id, date_from=timezone.now() - timedelta(days=1))

        assert [r.run_id for r in hits] == [str(recent.id)]

    def test_filters_by_date_to_for_cursor_iteration(self) -> None:
        """`date_to` is the upper bound the scout uses to walk past the result cap.

        Set it to the `created_at` of the oldest result on the prior page and the
        next call returns the *next* older slice.
        """
        old = _create_run(self.team)
        middle = _create_run(self.team)
        recent = _create_run(self.team)
        SignalScoutRun.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=14))
        middle_ts = timezone.now() - timedelta(days=7)
        SignalScoutRun.objects.filter(id=middle.id).update(created_at=middle_ts)
        SignalScoutRun.objects.filter(id=recent.id).update(created_at=timezone.now() - timedelta(hours=1))

        # Strict `<` bound: middle's own timestamp is excluded, only `old` is returned.
        hits = search_recent_runs(team_id=self.team.id, date_to=middle_ts)

        assert [r.run_id for r in hits] == [str(old.id)]

    def test_does_not_leak_runs_from_other_teams(self) -> None:
        from posthog.models import Team

        other = Team.objects.create(organization=self.organization, name="other")
        mine = _create_run(self.team)
        _create_run(other)

        hits = search_recent_runs(team_id=self.team.id)

        assert [r.run_id for r in hits] == [str(mine.id)]

    def test_limit_clamped_to_max(self) -> None:
        for _ in range(MAX_RUN_SEARCH_LIMIT + 5):
            _create_run(self.team)

        hits = search_recent_runs(team_id=self.team.id, limit=MAX_RUN_SEARCH_LIMIT + 50)

        assert len(hits) == MAX_RUN_SEARCH_LIMIT

    def test_summary_surfaces_status_from_linked_task_run(self) -> None:
        run = _create_run(self.team, task_run_status=TaskRun.Status.COMPLETED)

        hits = search_recent_runs(team_id=self.team.id, limit=1)

        assert hits[0].run_id == str(run.id)
        assert hits[0].status == TaskRun.Status.COMPLETED

    def test_text_filter_uses_ilike_on_summary(self) -> None:
        keep = _create_run(self.team, summary="Looked at /checkout 500s — nothing actionable")
        _create_run(self.team, summary="Scanned LLM costs, all normal")
        _create_run(self.team, summary="")

        hits = search_recent_runs(team_id=self.team.id, text="checkout")

        assert [h.run_id for h in hits] == [str(keep.id)]

    def test_summary_field_round_trips_through_projection(self) -> None:
        run = _create_run(self.team, summary="emit-free run; only known-noise patterns")

        hits = search_recent_runs(team_id=self.team.id, limit=1)

        assert hits[0].summary == "emit-free run; only known-noise patterns"
        detail = get_run(team_id=self.team.id, run_id=str(run.id))
        assert detail is not None
        assert detail.summary == "emit-free run; only known-noise patterns"


class TestGetRun(BaseTest):
    def test_returns_full_run_payload(self) -> None:
        run = _create_run(self.team)

        detail = get_run(team_id=self.team.id, run_id=str(run.id))

        assert detail is not None
        assert detail.run_id == str(run.id)
        assert detail.skill_name == "signals-scout-errors"
        assert detail.skill_version == 1
        assert detail.task_run_id == str(run.task_run_id)
        # Default-empty summary on rows that didn't go through the runner's finalize step.
        assert detail.summary == ""

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
    def test_creates_entry_with_default_lineage(self) -> None:
        entry = remember(team_id=self.team.id, key="known-noise", content="ignore /favicon 404s")

        row = SignalScratchpad.objects.get(team_id=self.team.id, key="known-noise")
        assert row.content == "ignore /favicon 404s"
        assert row.created_by_run_id is None
        assert entry.key == "known-noise"

    def test_idempotent_upsert_on_team_key(self) -> None:
        first = remember(team_id=self.team.id, key="k", content="v1")
        second = remember(team_id=self.team.id, key="k", content="v2")

        assert first.key == second.key
        rows = SignalScratchpad.objects.filter(team_id=self.team.id, key="k")
        assert rows.count() == 1
        row = rows.first()
        assert row is not None
        assert row.content == "v2"

    def test_upsert_preserves_original_creator_lineage(self) -> None:
        run = _create_run(self.team)
        # First write attributed to a run.
        remember(team_id=self.team.id, key="k", content="v1", run_id=str(run.id))
        # Second write has no run_id — must not overwrite the original creator.
        remember(team_id=self.team.id, key="k", content="v2")

        row = SignalScratchpad.objects.get(team_id=self.team.id, key="k")
        assert row.content == "v2"
        assert str(row.created_by_run_id) == str(run.id)

    def test_rejects_empty_key_or_content(self) -> None:
        with pytest.raises(InvalidScratchpadError):
            remember(team_id=self.team.id, key="", content="x")
        with pytest.raises(InvalidScratchpadError):
            remember(team_id=self.team.id, key="   ", content="x")
        with pytest.raises(InvalidScratchpadError):
            remember(team_id=self.team.id, key="k", content="")

    def test_rejects_content_over_max_length(self) -> None:
        remember(team_id=self.team.id, key="k", content="x" * MAX_SCRATCHPAD_CONTENT_LENGTH)
        with pytest.raises(InvalidScratchpadError):
            remember(team_id=self.team.id, key="k", content="x" * (MAX_SCRATCHPAD_CONTENT_LENGTH + 1))

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
    def test_deletes_entry(self) -> None:
        remember(team_id=self.team.id, key="k", content="v")

        result = forget(team_id=self.team.id, key="k")

        assert result is True
        assert not SignalScratchpad.objects.filter(team_id=self.team.id, key="k").exists()

    def test_returns_false_when_key_missing(self) -> None:
        assert forget(team_id=self.team.id, key="never-existed") is False


class TestSearchScratchpad(BaseTest):
    def test_returns_all_team_entries(self) -> None:
        SignalScratchpad.objects.create(team=self.team, key="a", content="alpha")
        SignalScratchpad.objects.create(team=self.team, key="b", content="beta")

        results = search_scratchpad(team_id=self.team.id)

        keys = {e.key for e in results}
        assert keys == {"a", "b"}

    def test_text_filter_uses_ilike_on_content_and_key(self) -> None:
        remember(team_id=self.team.id, key="k1", content="The CHECKOUT funnel is broken")
        remember(team_id=self.team.id, key="checkout-key", content="unrelated")
        remember(team_id=self.team.id, key="k2", content="Image loading is slow")

        results = search_scratchpad(team_id=self.team.id, text="checkout")

        keys = {e.key for e in results}
        # Matches on both content ('CHECKOUT' in k1) and key ('checkout-key').
        assert keys == {"k1", "checkout-key"}

    def test_does_not_leak_memories_from_other_teams(self) -> None:
        from posthog.models import Team

        other = Team.objects.create(organization=self.organization, name="other-team")
        remember(team_id=self.team.id, key="mine", content="mine")
        remember(team_id=other.id, key="theirs", content="theirs")

        results = search_scratchpad(team_id=self.team.id)

        assert all(e.key == "mine" for e in results)

    def test_limit_clamped_to_max(self) -> None:
        for i in range(MAX_SCRATCHPAD_SEARCH_LIMIT + 5):
            remember(team_id=self.team.id, key=f"k{i:03d}", content=f"c{i}")

        results = search_scratchpad(team_id=self.team.id, limit=MAX_SCRATCHPAD_SEARCH_LIMIT + 50)

        assert len(results) == MAX_SCRATCHPAD_SEARCH_LIMIT


# --- emit adapter tests ---


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
        many = [EvidenceEntry(source_product="logs", summary=f"e{i}") for i in range(MAX_EVIDENCE_ENTRIES + 1)]
        with pytest.raises(InvalidEmitError, match="evidence"):
            _validate_inputs("ok", 0.5, 0.5, many)

    def test_at_capacity_evidence_passes(self) -> None:
        many = [EvidenceEntry(source_product="logs", summary=f"e{i}") for i in range(MAX_EVIDENCE_ENTRIES)]
        # Should not raise.
        _validate_inputs("ok", 0.5, 0.5, many)


class TestBuildEmitExtra:
    """Pure shaping — no DB. Asserts the dict matches what `SignalsScoutSignalExtra` expects."""

    def _minimal(self) -> dict:
        return _build_extra(
            run_id="run-uuid",
            finding_id="finding-uuid",
            skill_name="signals-scout-errors",
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
        assert extra["scout_run_id"] == "run-uuid"
        assert extra["finding_id"] == "finding-uuid"
        assert extra["skill_name"] == "signals-scout-errors"
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
        # SignalsScoutSignalExtra.skill_version is float in posthog/schema.py.
        assert isinstance(extra["skill_version"], float)
        assert extra["skill_version"] == 2.0

    def test_full_extra_includes_all_optional_fields(self) -> None:
        extra = _build_extra(
            run_id="run-uuid",
            finding_id="finding-uuid",
            skill_name="signals-scout-errors",
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
        """Round-trip: the extra we build must pass `SignalsScoutSignalInput` validation
        — this is the contract `emit_signal` checks via `_SIGNAL_VARIANT_LOOKUP`."""
        from posthog.schema import SignalsScoutSignalInput

        extra = self._minimal()
        SignalsScoutSignalInput.model_validate(
            {
                "source_product": SOURCE_PRODUCT,
                "source_type": SOURCE_TYPE,
                "source_id": "run:run-uuid:finding:finding-uuid",
                "description": "d",
                "weight": 0.5,
                "extra": extra,
            }
        )


# --- emit_finding async tests ---


@pytest_asyncio.fixture
async def aorganization_emit():
    from posthog.models import Organization

    org = await database_sync_to_async(Organization.objects.create)(
        name="signals-scout-emit", is_ai_data_processing_approved=True
    )
    return org


@pytest_asyncio.fixture
async def ateam_emit(aorganization_emit):
    from posthog.models import Team

    from products.signals.backend.models import SignalSourceConfig

    team = await database_sync_to_async(Team.objects.create)(organization=aorganization_emit, name="emit-team")
    # The signals_scout source must be explicitly enabled per-team — emit_signal()
    # silently no-ops without it, and the harness preflight mirrors that gate.
    with team_scope(team.id, canonical=True):
        await database_sync_to_async(SignalSourceConfig.objects.create)(
            team=team,
            source_product="signals_scout",
            source_type="cross_source_issue",
            enabled=True,
        )
        # Seed a SignalScoutConfig so the run row's FK is valid.
        await database_sync_to_async(SignalScoutConfig.objects.create)(team=team)
        yield team


@pytest_asyncio.fixture
async def arun_emit(ateam_emit):
    config = await database_sync_to_async(SignalScoutConfig.objects.get)(team=ateam_emit)
    task_run = await database_sync_to_async(_make_task_run)(ateam_emit, status=TaskRun.Status.IN_PROGRESS)
    run = await database_sync_to_async(SignalScoutRun.objects.create)(
        task_run=task_run,
        team=ateam_emit,
        scout_config=config,
        skill_name="signals-scout-errors",
        skill_version=3,
    )
    return run


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_happy_path_calls_emit_signal_with_deterministic_source_id(ateam_emit, arun_emit):
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
    assert call_kwargs["extra"]["scout_run_id"] == str(arun_emit.id)
    assert call_kwargs["extra"]["finding_id"] == "f-happy"
    assert call_kwargs["extra"]["skill_name"] == "signals-scout-errors"
    assert call_kwargs["extra"]["skill_version"] == 3.0


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_validation_error_does_not_emit(ateam_emit, arun_emit):
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


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_propagates_emit_signal_exception(ateam_emit, arun_emit):
    # Scout-side idempotency was dropped in PR 2 review and the downstream pipeline
    # does NOT dedupe on source_id — a failed downstream emit surfaces back to the
    # caller, and a retry with the same finding_id would emit a second signal.
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
    # preflight, we surface the truth.
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


# --- emit_finding (team, run) ownership guard tests ---


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_finding_rejects_team_run_mismatch(aorganization_emit, ateam_emit, arun_emit) -> None:
    """If `team` and `run.team_id` disagree, refuse before reaching `emit_signal`.

    The view filters by `team_id` so this can't happen via the API path today,
    but the function self-defends for future direct callers (in-process MCP,
    management commands).
    """
    from posthog.models import Team

    other_team = await database_sync_to_async(Team.objects.create)(organization=aorganization_emit, name="other-team")

    with patch("products.signals.backend.api.emit_signal", new=AsyncMock()) as mock_emit:
        with pytest.raises(RuntimeError, match="does not own run"):
            await emit_finding(
                team=other_team,
                run=arun_emit,  # owned by ateam_emit, not other_team
                description="should be rejected",
                weight=0.5,
                confidence=0.5,
                evidence=[EvidenceEntry(source_product="logs", summary="x")],
            )
    mock_emit.assert_not_called()


def test_emit_finding_sync_rejects_team_run_mismatch(db) -> None:
    """Same guard as the async path, exercised against `emit_finding_sync`."""
    from posthog.models import Organization, Team

    org = Organization.objects.create(name="sync-mismatch-org", is_ai_data_processing_approved=True)
    owning_team = Team.objects.create(organization=org, name="owner")
    other_team = Team.objects.create(organization=org, name="other")
    with team_scope(owning_team.id, canonical=True):
        config = SignalScoutConfig.objects.create(team=owning_team)
        task_run = _make_task_run(owning_team, status=TaskRun.Status.IN_PROGRESS)
        run = SignalScoutRun.objects.create(
            task_run=task_run,
            team=owning_team,
            scout_config=config,
            skill_name="signals-scout-errors",
            skill_version=1,
        )

    with patch("products.signals.backend.api.emit_signal", new=AsyncMock()) as mock_emit:
        with pytest.raises(RuntimeError, match="does not own run"):
            emit_finding_sync(
                team=other_team,
                run=run,
                description="should be rejected",
                weight=0.5,
                confidence=0.5,
                evidence=[EvidenceEntry(source_product="logs", summary="x")],
            )
    mock_emit.assert_not_called()
