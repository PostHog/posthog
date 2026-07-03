import uuid
import datetime as dt
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

import psycopg.errors
from asgiref.sync import sync_to_async
from google.genai.errors import APIError
from parameterized import parameterized
from prometheus_client import REGISTRY
from structlog.testing import capture_logs
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    TimeoutError as TemporalTimeoutError,
    TimeoutType,
)

from posthog.schema import ReplayVisionScannerFindingSignalInput

from posthog.models import Organization, Team
from posthog.models.user import User
from posthog.redis import get_async_client
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.api.observation_progress import stream_observation_progress
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import (
    ReplayScanner,
    ScannerModel,
    ScannerScanScope,
    ScannerType,
)
from products.replay_vision.backend.quota import QuotaSnapshot
from products.replay_vision.backend.temporal import ApplyScannerWorkflow
from products.replay_vision.backend.temporal.activities.call_scanner_provider import (
    _extract_segments,
    _resolve_citations,
    call_scanner_provider_activity,
)
from products.replay_vision.backend.temporal.activities.cleanup_gemini_file import cleanup_gemini_file_activity
from products.replay_vision.backend.temporal.activities.create_observation import create_observation_activity
from products.replay_vision.backend.temporal.activities.embed_observation import embed_observation_activity
from products.replay_vision.backend.temporal.activities.emit_classifier_tags import emit_classifier_tags_activity
from products.replay_vision.backend.temporal.activities.emit_observation_event import emit_observation_event_activity
from products.replay_vision.backend.temporal.activities.emit_observation_signal import (
    SIGNAL_WEIGHT,
    emit_observation_signal_activity,
)
from products.replay_vision.backend.temporal.activities.ensure_session_asset import ensure_session_asset_activity
from products.replay_vision.backend.temporal.activities.fetch_session_events import fetch_session_events_activity
from products.replay_vision.backend.temporal.activities.observation_state import (
    mark_observation_failed_activity,
    mark_observation_ineligible_activity,
    mark_observation_running_activity,
    mark_observation_succeeded_activity,
)
from products.replay_vision.backend.temporal.activities.upload_video_to_gemini import upload_video_to_gemini_activity
from products.replay_vision.backend.temporal.errors import (
    INELIGIBLE_SESSION_ERROR_TYPE,
    SCANNER_FAILURE_ERROR_TYPE,
    FailureKind,
    IneligibleSessionError,
    IneligibleSessionKind,
    ScannerFailureError,
)
from products.replay_vision.backend.temporal.gemini_cleanup_sweep.constants import (
    REDIS_INDEX_KEY as _GEMINI_REDIS_INDEX_KEY,
    REDIS_KEY_PREFIX as _GEMINI_REDIS_KEY_PREFIX,
)
from products.replay_vision.backend.temporal.scanners.base import ChipSegment, Segment, SignalFinding, TextSegment
from products.replay_vision.backend.temporal.scanners.classifier import ClassifierOutput
from products.replay_vision.backend.temporal.scanners.monitor import MonitorOutput, MonitorScanner
from products.replay_vision.backend.temporal.scanners.scorer import ScorerOutput
from products.replay_vision.backend.temporal.scanners.summarizer import SummarizerOutput, SummarizerScanner
from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    generate_state_key,
    get_data_class_from_redis,
    store_data_in_redis,
)
from products.replay_vision.backend.temporal.types import (
    ApplyScannerInputs,
    CleanupGeminiFileInputs,
    CreateObservationInputs,
    CreateObservationOutput,
    EmbedObservationInputs,
    EmitClassifierTagsInputs,
    EmitObservationSignalInputs,
    EnsureSessionAssetInputs,
    EnsureSessionAssetOutput,
    EventTable,
    FetchSessionEventsInputs,
    MarkObservationFailedInputs,
    MarkObservationIneligibleInputs,
    MarkObservationRunningInputs,
    MarkObservationSucceededInputs,
    ScannerCallOutput,
    ScannerLlmInputs,
    ScannerResult,
    ScannerSnapshot,
    SessionMetadata,
    UploadedVideo,
)
from products.replay_vision.backend.temporal.workflow import (
    _activity_timeout_kind,
    _extract_kind_for_type,
    _root_cause_message,
)
from products.replay_vision.backend.tests.helpers import snapshot_for as _snapshot_for
from products.signals.backend.models import SignalSourceConfig


def test_scanner_snapshot_loads_rows_with_retired_model_and_provider_ids() -> None:
    snapshot = ScannerSnapshot.load_for(
        uuid.uuid4(),
        {
            "name": "old-scanner",
            "scanner_type": "monitor",
            "scanner_version": 1,
            "model": "gemini-1.0-flash-retired-preview",
            "provider": "hooli",
            "emits_signals": False,
            "scanner_config": {"prompt": "p"},
        },
    )
    assert snapshot.model == "gemini-1.0-flash-retired-preview"
    assert snapshot.provider == "hooli"
    # Snapshots persisted before scan scopes existed must keep loading as whole-recording.
    assert snapshot.scan_scope == ScannerScanScope.RECORDING
    assert snapshot.moments_config is None


def _make_scanner(**overrides) -> ReplayScanner:
    org = Organization.objects.create(name="vision-test-org")
    team = Team.objects.create(organization=org, name="vision-test-team")
    defaults: dict = {
        "team": team,
        "name": "t",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "p"},
        "model": ScannerModel.GEMINI_3_FLASH,
    }
    defaults.update(overrides)
    return ReplayScanner.objects.create(**defaults)


def _make_observation(scanner: ReplayScanner, **overrides) -> ReplayObservation:
    defaults: dict = {
        "scanner": scanner,
        "team": scanner.team,
        "session_id": "sess-1",
        "triggered_by": ObservationTrigger.ON_DEMAND,
        "scanner_snapshot": _snapshot_for(scanner),
    }
    defaults.update(overrides)
    return ReplayObservation.objects.create(**defaults)


@pytest.mark.django_db(transaction=True)
class TestCreateObservationActivity:
    def test_creates_row_in_pending_with_workflow_id_and_snapshot(self) -> None:
        scanner = _make_scanner()
        result = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
                workflow_id="wf-xyz",
            )
        )

        assert result.was_created is True
        assert result.observation_id is not None
        observation = ReplayObservation.objects.get(id=result.observation_id)
        assert observation.status == ObservationStatus.PENDING
        assert observation.workflow_id == "wf-xyz"
        assert observation.session_id == "sess-1"
        assert observation.triggered_by == ObservationTrigger.ON_DEMAND
        assert observation.scanner_snapshot["name"] == scanner.name
        assert observation.scanner_snapshot["scanner_type"] == str(scanner.scanner_type)
        assert observation.scanner_snapshot["scanner_version"] == scanner.scanner_version
        assert observation.scanner_snapshot["model"] == str(scanner.model)
        assert observation.scanner_snapshot["provider"] == str(scanner.provider)
        assert observation.scanner_snapshot["emits_signals"] == scanner.emits_signals
        assert observation.scanner_snapshot["scanner_config"] == scanner.scanner_config
        assert observation.started_at is None  # set when transitioning to running, not here
        assert observation.completed_at is None

    def test_snapshot_is_frozen_against_later_scanner_edits(self) -> None:
        scanner = _make_scanner()
        original_config = dict(scanner.scanner_config)
        result = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.SCHEDULE,
                triggered_by_user_id=None,
                workflow_id="wf-1",
            )
        )

        scanner.scanner_config = {"prompt": "completely different prompt"}
        scanner.save()

        assert result.observation_id is not None
        observation = ReplayObservation.objects.get(id=result.observation_id)
        assert observation.scanner_snapshot["scanner_config"] == original_config

    def test_returns_existing_observation_on_unique_conflict(self) -> None:
        scanner = _make_scanner()
        existing = _make_observation(scanner, session_id="sess-dup")

        result = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-dup",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
                workflow_id="wf-second",
            )
        )

        assert result == CreateObservationOutput(
            observation_id=existing.id, was_created=False, scanner_type=ScannerType.MONITOR
        )
        # The original row wasn't touched.
        existing.refresh_from_db()
        assert existing.workflow_id != "wf-second"

    @pytest.mark.parametrize(
        "status, completed_at, expect_reclaimed",
        [
            pytest.param(ObservationStatus.PENDING, None, True, id="own_pending_insert_is_reclaimed"),
            pytest.param(ObservationStatus.FAILED, timezone.now(), False, id="own_terminal_row_is_not_reclaimed"),
        ],
    )
    def test_unique_conflict_with_own_workflow_id(
        self, status: str, completed_at: dt.datetime | None, expect_reclaimed: bool
    ) -> None:
        # A lost-result retry hits the UNIQUE constraint on its own insert; disowning it strands the row in `pending`.
        scanner = _make_scanner()
        existing = _make_observation(
            scanner, session_id="sess-retry", workflow_id="wf-retry", status=status, completed_at=completed_at
        )

        result = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-retry",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
                workflow_id="wf-retry",
            )
        )

        assert result.observation_id == existing.id
        assert result.was_created is expect_reclaimed

    def test_propagates_non_unique_integrity_errors(self) -> None:
        # FK/CHECK violations must surface as activity failures, not silently fall into the dedup path.
        scanner = _make_scanner()
        fk_error = IntegrityError("insert or update on table violates foreign key constraint")
        fk_error.__cause__ = psycopg.errors.ForeignKeyViolation("violation")

        with patch.object(ReplayObservation.objects, "create", side_effect=fk_error):
            with pytest.raises(IntegrityError):
                create_observation_activity(
                    CreateObservationInputs(
                        scanner_id=scanner.id,
                        team_id=scanner.team_id,
                        session_id="sess-fk",
                        triggered_by=ObservationTrigger.ON_DEMAND,
                        triggered_by_user_id=None,
                        workflow_id="wf-fk",
                    )
                )

        assert not ReplayObservation.objects.filter(scanner=scanner, session_id="sess-fk").exists()

    @pytest.mark.parametrize(
        "use_real_scanner_id, team_id_offset",
        [
            pytest.param(False, 0, id="scanner_does_not_exist"),
            pytest.param(True, 999, id="scanner_belongs_to_other_team"),
        ],
    )
    def test_raises_when_scanner_not_found_for_team(self, use_real_scanner_id: bool, team_id_offset: int) -> None:
        scanner = _make_scanner()
        scanner_id = scanner.id if use_real_scanner_id else uuid.uuid4()
        team_id = scanner.team_id + team_id_offset

        with pytest.raises(ValueError):
            create_observation_activity(
                CreateObservationInputs(
                    scanner_id=scanner_id,
                    team_id=team_id,
                    session_id="sess-1",
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=None,
                    workflow_id="wf-1",
                )
            )

    def test_raises_when_user_is_not_in_scanner_organization(self) -> None:
        scanner = _make_scanner()
        outsider_org = Organization.objects.create(name="other-org")
        outsider = User.objects.create_and_join(organization=outsider_org, email="x@x.com", password=None)

        with pytest.raises(ValueError, match="not a member"):
            create_observation_activity(
                CreateObservationInputs(
                    scanner_id=scanner.id,
                    team_id=scanner.team_id,
                    session_id="sess-1",
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=outsider.id,
                    workflow_id="wf-1",
                )
            )

    def test_accepts_user_in_scanner_organization(self) -> None:
        scanner = _make_scanner()
        member = User.objects.create_and_join(organization=scanner.team.organization, email="m@m.com", password=None)

        result = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=member.id,
                workflow_id="wf-1",
            )
        )
        assert result.was_created is True

    def test_skips_insert_when_monthly_quota_exhausted(self) -> None:
        scanner = _make_scanner()
        with patch(
            "products.replay_vision.backend.temporal.activities.create_observation.compute_quota_snapshot"
        ) as mock_snapshot:
            mock_snapshot.return_value = QuotaSnapshot(
                monthly_quota=1,
                usage_this_month=1,
                period_start=dt.datetime.now(dt.UTC),
                period_end=dt.datetime.now(dt.UTC),
                projected_monthly_observations=0,
            )
            result = create_observation_activity(
                CreateObservationInputs(
                    scanner_id=scanner.id,
                    team_id=scanner.team_id,
                    session_id="sess-quota",
                    triggered_by=ObservationTrigger.SCHEDULE,
                    triggered_by_user_id=None,
                    workflow_id="wf-quota",
                )
            )
        assert result == CreateObservationOutput(
            observation_id=None, was_created=False, scanner_type=scanner.scanner_type
        )
        assert not ReplayObservation.objects.filter(scanner=scanner, session_id="sess-quota").exists()


@pytest.mark.django_db(transaction=True)
class TestObservationStateActivities:
    def test_mark_running_stamps_started_at(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, workflow_id="wf-1")
        assert observation.status == ObservationStatus.PENDING

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.RUNNING
        assert observation.workflow_id == "wf-1"
        assert observation.started_at is not None

    def test_mark_failed_records_reason_and_completed_at(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner)
        observation.status = ObservationStatus.RUNNING
        observation.started_at = timezone.now()
        observation.save(update_fields=["status", "started_at"])

        mark_observation_failed_activity(
            MarkObservationFailedInputs(
                observation_id=observation.id, error_reason="bad output", scanner_type=ScannerType.MONITOR
            )
        )

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.FAILED
        assert observation.error_reason == "bad output"
        assert observation.completed_at is not None

    def test_mark_ineligible_records_kind_reason_and_completed_at(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, status=ObservationStatus.RUNNING, started_at=timezone.now())

        mark_observation_ineligible_activity(
            MarkObservationIneligibleInputs(
                observation_id=observation.id,
                error_reason="too_short:only 5s long",
                scanner_type=ScannerType.MONITOR,
            )
        )

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.INELIGIBLE
        assert observation.error_reason == "too_short:only 5s long"
        assert observation.completed_at is not None

    @pytest.mark.parametrize(
        "terminal_status",
        [ObservationStatus.SUCCEEDED, ObservationStatus.FAILED, ObservationStatus.INELIGIBLE],
    )
    def test_terminal_status_is_not_overwritten_by_state_activities(self, terminal_status: str) -> None:
        # Bounded UPDATE protects against retries that race past a settled row.
        scanner = _make_scanner()
        observation = _make_observation(scanner)
        observation.status = terminal_status
        observation.completed_at = timezone.now()
        observation.error_reason = "original"
        observation.save(update_fields=["status", "completed_at", "error_reason"])

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))
        mark_observation_failed_activity(
            MarkObservationFailedInputs(
                observation_id=observation.id, error_reason="late failure", scanner_type=ScannerType.MONITOR
            )
        )

        observation.refresh_from_db()
        assert observation.status == terminal_status
        assert observation.error_reason == "original"

    def test_mark_running_is_idempotent_against_already_running_rows(self) -> None:
        # `started_at` must survive at-least-once retries; duration metrics depend on it.
        scanner = _make_scanner()
        observation = _make_observation(scanner)
        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))
        observation.refresh_from_db()
        first_started_at = observation.started_at
        assert first_started_at is not None

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))
        observation.refresh_from_db()
        assert observation.started_at == first_started_at

    def test_mark_succeeded_stamps_lifecycle_metadata_and_persists_result(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, status=ObservationStatus.RUNNING, started_at=timezone.now())
        result = ScannerResult(model_output=MonitorOutput(verdict="yes", reasoning="ok", confidence=0.9))

        mark_observation_succeeded_activity(
            MarkObservationSucceededInputs(
                observation_id=observation.id, scanner_result=result, scanner_type=ScannerType.MONITOR
            )
        )

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.SUCCEEDED
        assert observation.completed_at is not None
        assert observation.scanner_result == result.model_dump(mode="json")

    def test_mark_succeeded_does_not_overwrite_terminal_status(self) -> None:
        # Bounded UPDATE: failed/succeeded rows are sticky.
        scanner = _make_scanner()
        observation = _make_observation(
            scanner, status=ObservationStatus.FAILED, error_reason="prior", completed_at=timezone.now()
        )
        result = ScannerResult(model_output=MonitorOutput(verdict="yes", reasoning="late", confidence=0.9))

        mark_observation_succeeded_activity(
            MarkObservationSucceededInputs(
                observation_id=observation.id, scanner_result=result, scanner_type=ScannerType.MONITOR
            )
        )

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.FAILED
        assert observation.completed_at is not None
        assert observation.scanner_result == {}  # not overwritten

    def test_mark_succeeded_writes_usage_receipt(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, status=ObservationStatus.RUNNING, started_at=timezone.now())
        result = ScannerResult(model_output=MonitorOutput(verdict="yes", reasoning="ok", confidence=0.9))

        mark_observation_succeeded_activity(
            MarkObservationSucceededInputs(
                observation_id=observation.id, scanner_result=result, scanner_type=ScannerType.MONITOR
            )
        )

        receipts = ReplayObservationUsage.objects.filter(observation_id=observation.id)
        assert receipts.count() == 1
        receipt = receipts.get()
        assert receipt.organization_id == observation.team.organization_id
        assert receipt.observation_created_at == observation.created_at

    def test_mark_succeeded_usage_receipt_is_idempotent(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, status=ObservationStatus.RUNNING, started_at=timezone.now())
        result = ScannerResult(model_output=MonitorOutput(verdict="yes", reasoning="ok", confidence=0.9))
        inputs = MarkObservationSucceededInputs(
            observation_id=observation.id, scanner_result=result, scanner_type=ScannerType.MONITOR
        )

        mark_observation_succeeded_activity(inputs)
        mark_observation_succeeded_activity(inputs)  # retry: the transition is sticky, so no second receipt

        assert ReplayObservationUsage.objects.filter(observation_id=observation.id).count() == 1

    def test_mark_failed_writes_no_usage_receipt(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, status=ObservationStatus.RUNNING, started_at=timezone.now())

        mark_observation_failed_activity(
            MarkObservationFailedInputs(
                observation_id=observation.id,
                error_reason="provider_rejected:nope",
                scanner_type=ScannerType.MONITOR,
            )
        )

        assert ReplayObservationUsage.objects.filter(observation_id=observation.id).count() == 0


def _counter_value(metric_name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(metric_name, labels) or 0.0


@pytest.mark.django_db(transaction=True)
class TestObservationStateMetricsAndLogs:
    def test_mark_succeeded_increments_observations_counter_and_logs(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, status=ObservationStatus.RUNNING, started_at=timezone.now())
        result = ScannerResult(model_output=MonitorOutput(verdict="yes", reasoning="ok", confidence=0.8))
        before = _counter_value("replay_vision_observations_total", status="succeeded", scanner_type="monitor")

        with capture_logs() as logs:
            mark_observation_succeeded_activity(
                MarkObservationSucceededInputs(
                    observation_id=observation.id, scanner_result=result, scanner_type=ScannerType.MONITOR
                )
            )

        after = _counter_value("replay_vision_observations_total", status="succeeded", scanner_type="monitor")
        assert after == before + 1
        events = [r for r in logs if r.get("event") == "replay_vision.observation.succeeded"]
        assert len(events) == 1
        assert events[0]["scanner_type"] == "monitor"
        assert events[0]["observation_id"] == str(observation.id)

    def test_mark_failed_increments_observations_and_failure_kinds(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, status=ObservationStatus.RUNNING, started_at=timezone.now())
        before_obs = _counter_value("replay_vision_observations_total", status="failed", scanner_type="monitor")
        before_kind = _counter_value(
            "replay_vision_failure_kinds_total", kind="provider_rejected", scanner_type="monitor"
        )

        with capture_logs() as logs:
            mark_observation_failed_activity(
                MarkObservationFailedInputs(
                    observation_id=observation.id,
                    error_reason="provider_rejected:Gemini said no",
                    scanner_type=ScannerType.MONITOR,
                )
            )

        assert _counter_value("replay_vision_observations_total", status="failed", scanner_type="monitor") == (
            before_obs + 1
        )
        assert _counter_value(
            "replay_vision_failure_kinds_total", kind="provider_rejected", scanner_type="monitor"
        ) == (before_kind + 1)
        events = [r for r in logs if r.get("event") == "replay_vision.observation.failed"]
        assert len(events) == 1
        assert events[0]["kind"] == "provider_rejected"
        assert events[0]["scanner_type"] == "monitor"

    def test_mark_failed_with_unparseable_error_reason_labels_kind_unknown(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, status=ObservationStatus.RUNNING, started_at=timezone.now())
        before = _counter_value("replay_vision_failure_kinds_total", kind="unknown", scanner_type="monitor")

        mark_observation_failed_activity(
            MarkObservationFailedInputs(
                observation_id=observation.id,
                error_reason="no colon here",
                scanner_type=ScannerType.MONITOR,
            )
        )

        assert _counter_value("replay_vision_failure_kinds_total", kind="unknown", scanner_type="monitor") == (
            before + 1
        )

    def test_mark_ineligible_increments_observations_and_ineligible_kinds(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, status=ObservationStatus.RUNNING, started_at=timezone.now())
        before_obs = _counter_value("replay_vision_observations_total", status="ineligible", scanner_type="monitor")
        before_kind = _counter_value("replay_vision_ineligible_kinds_total", kind="too_short")

        with capture_logs() as logs:
            mark_observation_ineligible_activity(
                MarkObservationIneligibleInputs(
                    observation_id=observation.id,
                    error_reason="too_short:only 5s long",
                    scanner_type=ScannerType.MONITOR,
                )
            )

        assert _counter_value("replay_vision_observations_total", status="ineligible", scanner_type="monitor") == (
            before_obs + 1
        )
        assert _counter_value("replay_vision_ineligible_kinds_total", kind="too_short") == before_kind + 1
        events = [r for r in logs if r.get("event") == "replay_vision.observation.ineligible"]
        assert len(events) == 1
        assert events[0]["kind"] == "too_short"

    def test_activity_duration_histogram_records_success_observation(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, status=ObservationStatus.RUNNING, started_at=timezone.now())
        result = ScannerResult(model_output=MonitorOutput(verdict="yes", reasoning="ok", confidence=0.8))
        labels = {"activity": "mark_observation_succeeded_activity", "status": "succeeded"}
        before = _counter_value("replay_vision_activity_duration_seconds_count", **labels)

        mark_observation_succeeded_activity(
            MarkObservationSucceededInputs(
                observation_id=observation.id, scanner_result=result, scanner_type=ScannerType.MONITOR
            )
        )

        assert _counter_value("replay_vision_activity_duration_seconds_count", **labels) == before + 1

    @pytest.mark.parametrize(
        "error_reason, expected_kind",
        [
            ("provider_rejected:bad video", "provider_rejected"),
            ("internal_error:", "internal_error"),  # empty message still parses kind
            ("not a kind:something", "unknown"),  # leading text isn't an enum value
            ("no colon here", "unknown"),
            (":message", "unknown"),  # leading colon
            ("", "unknown"),
            ("provider_rejected:has:more:colons", "provider_rejected"),  # only first colon splits
        ],
    )
    def test_failure_kind_parser_validates_against_enum(self, error_reason: str, expected_kind: str) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, status=ObservationStatus.RUNNING, started_at=timezone.now())
        before = _counter_value("replay_vision_failure_kinds_total", kind=expected_kind, scanner_type="monitor")

        mark_observation_failed_activity(
            MarkObservationFailedInputs(
                observation_id=observation.id, error_reason=error_reason, scanner_type=ScannerType.MONITOR
            )
        )

        assert _counter_value("replay_vision_failure_kinds_total", kind=expected_kind, scanner_type="monitor") == (
            before + 1
        )

    @pytest.mark.parametrize(
        "observation_status, metric_status, log_event, run_activity",
        [
            (
                ObservationStatus.FAILED,
                "failed",
                "replay_vision.observation.failed",
                lambda obs_id: mark_observation_failed_activity(
                    MarkObservationFailedInputs(
                        observation_id=obs_id,
                        error_reason="internal_error:late retry",
                        scanner_type=ScannerType.MONITOR,
                    )
                ),
            ),
            (
                ObservationStatus.INELIGIBLE,
                "ineligible",
                "replay_vision.observation.ineligible",
                lambda obs_id: mark_observation_ineligible_activity(
                    MarkObservationIneligibleInputs(
                        observation_id=obs_id,
                        error_reason="too_short:late retry",
                        scanner_type=ScannerType.MONITOR,
                    )
                ),
            ),
            (
                ObservationStatus.SUCCEEDED,
                "succeeded",
                "replay_vision.observation.succeeded",
                lambda obs_id: mark_observation_succeeded_activity(
                    MarkObservationSucceededInputs(
                        observation_id=obs_id,
                        scanner_result=ScannerResult(
                            model_output=MonitorOutput(verdict="yes", reasoning="late", confidence=0.8)
                        ),
                        scanner_type=ScannerType.MONITOR,
                    )
                ),
            ),
        ],
        ids=["failed", "ineligible", "succeeded"],
    )
    def test_no_counter_or_log_when_update_affects_zero_rows(
        self,
        observation_status: ObservationStatus,
        metric_status: str,
        log_event: str,
        run_activity,
    ) -> None:
        # Idempotent retry against an already-terminal row must not double-count or re-log.
        scanner = _make_scanner()
        observation = _make_observation(
            scanner, status=observation_status, completed_at=timezone.now(), error_reason="original"
        )
        before_obs = _counter_value("replay_vision_observations_total", status=metric_status, scanner_type="monitor")

        with capture_logs() as logs:
            run_activity(observation.id)

        assert (
            _counter_value("replay_vision_observations_total", status=metric_status, scanner_type="monitor")
            == before_obs
        )
        assert [r for r in logs if r.get("event") == log_event] == []

    def test_activity_duration_histogram_records_failure_observation(self) -> None:
        scanner = _make_scanner()
        observation = _make_observation(scanner, status=ObservationStatus.PENDING)
        labels = {"activity": "mark_observation_succeeded_activity", "status": "failed"}
        before = _counter_value("replay_vision_activity_duration_seconds_count", **labels)

        with patch(
            "products.replay_vision.backend.temporal.activities.observation_state.ReplayObservation.objects",
            new_callable=MagicMock,
        ) as mock_objects:
            mock_objects.filter.return_value.update.side_effect = RuntimeError("db blew up")
            with pytest.raises(RuntimeError):
                mark_observation_succeeded_activity(
                    MarkObservationSucceededInputs(
                        observation_id=observation.id,
                        scanner_result=ScannerResult(
                            model_output=MonitorOutput(verdict="yes", reasoning="ok", confidence=0.8)
                        ),
                        scanner_type=ScannerType.MONITOR,
                    )
                )

        assert _counter_value("replay_vision_activity_duration_seconds_count", **labels) == before + 1


@pytest.mark.django_db(transaction=True)
class TestFetchSessionEventsActivity:
    def _make_session_replay_events_mock(
        self,
        metadata: dict | None,
        pages: list[tuple],
    ) -> MagicMock:
        """Pages may be 2-tuples (columns, rows) or 3-tuples (columns, rows, has_more); has_more defaults to False."""
        normalized = [page if len(page) == 3 else (*page, False) for page in pages]
        mock_obj = MagicMock(spec=SessionReplayEvents)
        mock_obj.get_metadata.return_value = metadata
        mock_obj.get_events.side_effect = normalized
        return mock_obj

    @pytest.mark.asyncio
    async def test_stashes_scanner_llm_inputs_in_redis(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        end = dt.datetime(2026, 5, 12, 10, 5, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": end, "duration": 300, "active_seconds": 200}

        mock_obj = self._make_session_replay_events_mock(
            metadata,
            [(["event", "timestamp", "$session_id"], [("$pageview", start, "sess-1")])],
        )

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(
                    observation_id=observation_id,
                    team_id=scanner.team_id,
                    session_id="sess-1",
                )
            )

        redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        stored = await get_data_class_from_redis(redis_client, key, target_class=ScannerLlmInputs)
        assert stored is not None
        assert stored.session_id == "sess-1"
        assert stored.team_id == scanner.team_id
        assert stored.events.columns == ["event_uuid", "event", "timestamp", "$session_id"]
        assert stored.metadata.start_time == start
        assert stored.metadata.end_time == end
        assert stored.metadata.duration_seconds == 300.0
        assert len(stored.events.rows) == 1
        assert stored.events.rows[0][1:] == ["$pageview", "2026-05-12T10:00:00Z", "sess-1"]

    @pytest.mark.asyncio
    async def test_fetches_a_single_page_with_the_configured_limit(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": start, "duration": 60, "active_seconds": 30}
        page_rows = [("$pageview", start, f"sess-{i}") for i in range(50)]
        mock_obj = self._make_session_replay_events_mock(
            metadata, [(["event", "timestamp", "$session_id"], page_rows, False)]
        )

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(observation_id=observation_id, team_id=scanner.team_id, session_id="sess-1")
            )

        assert mock_obj.get_events.call_count == 1
        assert mock_obj.get_events.call_args_list[0].kwargs["page"] == 0
        assert mock_obj.get_events.call_args_list[0].kwargs["limit"] == 2000

        redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        stored = await get_data_class_from_redis(redis_client, key, target_class=ScannerLlmInputs)
        assert stored is not None
        assert len(stored.events.rows) == 50

    @pytest.mark.asyncio
    async def test_is_idempotent_when_redis_already_has_payload(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        # Pre-populate Redis as if a previous run had finished.
        redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        existing = ScannerLlmInputs(
            session_id="sess-1",
            team_id=scanner.team_id,
            events=EventTable(columns=["event"], rows=[["$pageview"]]),
            metadata=SessionMetadata(
                start_time=dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC),
                end_time=dt.datetime(2026, 5, 12, 10, 5, 0, tzinfo=dt.UTC),
                duration_seconds=300.0,
            ),
        )
        await store_data_in_redis(redis_client, key, existing.model_dump_json())

        mock_obj = MagicMock(spec=SessionReplayEvents)
        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(
                    observation_id=observation_id,
                    team_id=scanner.team_id,
                    session_id="sess-1",
                )
            )

        mock_obj.get_metadata.assert_not_called()
        mock_obj.get_events.assert_not_called()

    @pytest.mark.parametrize(
        "metadata,expected_kind,expected_substring",
        [
            (None, "no_recording", "No replay metadata"),
            (
                {
                    "start_time": dt.datetime(2026, 5, 12, tzinfo=dt.UTC),
                    "end_time": dt.datetime(2026, 5, 12, 0, 0, 5, tzinfo=dt.UTC),
                    "duration": 5,  # under 15s floor
                    "active_seconds": 5,
                },
                "too_short",
                "Only 5",
            ),
            (
                {
                    "start_time": dt.datetime(2026, 5, 12, tzinfo=dt.UTC),
                    "end_time": dt.datetime(2026, 5, 12, 0, 5, tzinfo=dt.UTC),
                    "duration": 300,
                    "active_seconds": 3,  # under 10s floor
                },
                "too_inactive",
                "Only 3s of active",
            ),
            (
                {
                    "start_time": dt.datetime(2026, 5, 12, tzinfo=dt.UTC),
                    "end_time": dt.datetime(2026, 5, 12, 2, tzinfo=dt.UTC),
                    "duration": 7200,
                    "active_seconds": 5000,  # over 3600 cap
                },
                "too_long",
                "5000s of active",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_raises_ineligible_session_error_with_kind(
        self, metadata: dict | None, expected_kind: str, expected_substring: str
    ) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        mock_obj = self._make_session_replay_events_mock(metadata, [(["event"], [("$pageview",)])])

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            with pytest.raises(IneligibleSessionError) as exc_info:
                await fetch_session_events_activity(
                    FetchSessionEventsInputs(
                        observation_id=observation_id, team_id=scanner.team_id, session_id="sess-x"
                    )
                )

        assert exc_info.value.non_retryable is True
        assert exc_info.value.type == INELIGIBLE_SESSION_ERROR_TYPE
        assert exc_info.value.kind == expected_kind
        # Kind is also in `details[0]` so the workflow can read it off the wire-serialized ApplicationError.
        assert exc_info.value.details == (expected_kind,)
        assert expected_substring in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_ineligible_no_events_when_session_returns_empty_pages(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        metadata = {
            "start_time": dt.datetime(2026, 5, 12, tzinfo=dt.UTC),
            "end_time": dt.datetime(2026, 5, 12, 0, 5, tzinfo=dt.UTC),
            "duration": 300,
            "active_seconds": 200,
        }
        # Empty columns + no rows triggers `_fetch_payload` to return None.
        mock_obj = self._make_session_replay_events_mock(metadata, [([], [])])

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            with pytest.raises(IneligibleSessionError) as exc_info:
                await fetch_session_events_activity(
                    FetchSessionEventsInputs(
                        observation_id=observation_id, team_id=scanner.team_id, session_id="sess-empty"
                    )
                )

        assert exc_info.value.non_retryable is True
        assert exc_info.value.kind == "no_events"
        assert exc_info.value.details == ("no_events",)

    @pytest.mark.asyncio
    async def test_requests_extra_fields_and_event_blocklist(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": start, "duration": 60, "active_seconds": 30}
        mock_obj = self._make_session_replay_events_mock(metadata, [(["event"], [("$pageview",)])])

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(observation_id=observation_id, team_id=scanner.team_id, session_id="sess-1")
            )

        kwargs = mock_obj.get_events.call_args_list[0].kwargs
        assert kwargs["events_to_ignore"] == ["$feature_flag_called"]
        assert "elements_chain_ids" in kwargs["extra_fields"]
        assert "properties.$exception_types" in kwargs["extra_fields"]
        assert "properties.$exception_values" in kwargs["extra_fields"]

    @pytest.mark.asyncio
    async def test_simplifies_repeated_urls_and_window_ids(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": start, "duration": 60, "active_seconds": 30}
        long_url = "https://app.example.com/very/long/path?with=querystring&that=repeats"
        win = "01931abc-1234-7890-abcd-ef0123456789"
        mock_obj = self._make_session_replay_events_mock(
            metadata,
            [
                (
                    ["event", "$current_url", "$window_id"],
                    [
                        ("$pageview", long_url, win),
                        ("button_click", long_url, win),
                        ("$pageview", long_url + "/sub", win),
                    ],
                )
            ],
        )

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(observation_id=observation_id, team_id=scanner.team_id, session_id="sess-1")
            )

        redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        stored = await get_data_class_from_redis(redis_client, key, target_class=ScannerLlmInputs)
        assert stored is not None
        # 2 unique URLs, 1 unique window — mappings are reverse (short -> actual).
        assert stored.url_mapping == {"url_1": long_url, "url_2": long_url + "/sub"}
        assert stored.window_mapping == {"window_1": win}
        # Row values for $current_url and $window_id are now the short tokens.
        url_col = stored.events.columns.index("$current_url")
        window_col = stored.events.columns.index("$window_id")
        assert [row[url_col] for row in stored.events.rows] == ["url_1", "url_1", "url_2"]
        assert {row[window_col] for row in stored.events.rows} == {"window_1"}

    @pytest.mark.asyncio
    async def test_deduplicates_identical_events_by_hash(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": start, "duration": 60, "active_seconds": 30}
        mock_obj = self._make_session_replay_events_mock(
            metadata,
            [
                (
                    ["event", "timestamp"],
                    [
                        ("rageclick", start),
                        ("rageclick", start),  # exact dup, drops
                        ("rageclick", start),  # exact dup, drops
                        ("$pageview", start),
                    ],
                )
            ],
        )

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(observation_id=observation_id, team_id=scanner.team_id, session_id="sess-1")
            )

        redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        stored = await get_data_class_from_redis(redis_client, key, target_class=ScannerLlmInputs)
        assert stored is not None
        assert len(stored.events.rows) == 2  # rageclick collapsed, plus the $pageview

    @pytest.mark.asyncio
    async def test_deduplicates_identical_content_despite_distinct_uuids(self) -> None:
        # `uuid` is fetched per event but excluded from the dedup hash — otherwise identical events never collapse.
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": start, "duration": 60, "active_seconds": 30}
        mock_obj = self._make_session_replay_events_mock(
            metadata,
            [
                (
                    ["event", "timestamp", "uuid"],
                    [
                        ("rageclick", start, "00000000-0000-0000-0000-000000000001"),
                        ("rageclick", start, "00000000-0000-0000-0000-000000000002"),  # distinct uuid, same content
                        ("rageclick", start, "00000000-0000-0000-0000-000000000003"),
                        ("$pageview", start, "00000000-0000-0000-0000-000000000004"),
                    ],
                )
            ],
        )

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(observation_id=observation_id, team_id=scanner.team_id, session_id="sess-1")
            )

        redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        stored = await get_data_class_from_redis(redis_client, key, target_class=ScannerLlmInputs)
        assert stored is not None
        assert len(stored.events.rows) == 2  # rageclick collapsed, $pageview kept
        assert "event_uuid" in stored.events.columns
        assert "uuid" not in stored.events.columns
        assert set(stored.event_timestamps.keys()) == {
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000004",
        }

    @pytest.mark.asyncio
    async def test_session_metadata_round_trips_to_payload(self) -> None:
        # `RecordingMetadata` uses `first_url` (not `start_url`) and has no `inactive_seconds` — we derive it from duration.
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        metadata = {
            "start_time": start,
            "end_time": start,
            "duration": 240,
            "active_seconds": 180,
            "click_count": 23,
            "keypress_count": 41,
            "mouse_activity_count": 156,
            "first_url": "https://app.example.com/dashboard",
            "console_error_count": 3,
        }
        mock_obj = self._make_session_replay_events_mock(metadata, [(["event"], [("$pageview",)])])

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(observation_id=observation_id, team_id=scanner.team_id, session_id="sess-1")
            )

        redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        stored = await get_data_class_from_redis(redis_client, key, target_class=ScannerLlmInputs)
        assert stored is not None
        m = stored.metadata
        assert m.active_seconds == 180
        assert m.inactive_seconds == 60  # derived: duration (240) − active (180)
        assert m.click_count == 23
        assert m.start_url == "https://app.example.com/dashboard"
        assert m.console_error_count == 3

    @pytest.mark.asyncio
    async def test_loads_every_page_until_source_is_exhausted(self) -> None:
        # No event cap: when a page reports `has_more`, keep paging and load the whole session.
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": start, "duration": 60, "active_seconds": 30}
        cols = ["event", "timestamp", "$session_id"]
        mock_obj = self._make_session_replay_events_mock(
            metadata,
            [
                (cols, [("$pageview", start, "a"), ("$autocapture", start, "b")], True),
                (cols, [("$click", start, "c")], False),
            ],
        )

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(observation_id=observation_id, team_id=scanner.team_id, session_id="sess-1")
            )

        redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        stored = await get_data_class_from_redis(redis_client, key, target_class=ScannerLlmInputs)
        assert stored is not None
        assert mock_obj.get_events.call_count == 2  # paged through both, not capped at one page
        assert len(stored.events.rows) == 3  # every event from both pages

    @pytest.mark.asyncio
    async def test_stops_paging_once_no_more(self) -> None:
        # `has_more=False` on the first page → no further page fetched.
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": start, "duration": 60, "active_seconds": 30}
        mock_obj = self._make_session_replay_events_mock(
            metadata, [(["event", "timestamp", "$session_id"], [("$pageview", start, "a")], False)]
        )

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(observation_id=observation_id, team_id=scanner.team_id, session_id="sess-1")
            )

        assert mock_obj.get_events.call_count == 1

    @pytest.mark.asyncio
    async def test_raises_non_retryable_when_session_duration_below_min(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        # 5s is under the 15s minimum.
        metadata = {"start_time": start, "end_time": start, "duration": 5, "active_seconds": 3}
        mock_obj = self._make_session_replay_events_mock(metadata, [(["event"], [("$pageview",)])])

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            with pytest.raises(ApplicationError) as exc_info:
                await fetch_session_events_activity(
                    FetchSessionEventsInputs(
                        observation_id=observation_id, team_id=scanner.team_id, session_id="sess-1"
                    )
                )
            assert exc_info.value.non_retryable is True
            assert "5" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_non_retryable_when_active_seconds_below_min(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        # 60s duration passes; 3s active is under the 10s minimum.
        metadata = {"start_time": start, "end_time": start, "duration": 60, "active_seconds": 3}
        mock_obj = self._make_session_replay_events_mock(metadata, [(["event"], [("$pageview",)])])

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            with pytest.raises(ApplicationError) as exc_info:
                await fetch_session_events_activity(
                    FetchSessionEventsInputs(
                        observation_id=observation_id, team_id=scanner.team_id, session_id="sess-1"
                    )
                )
            assert exc_info.value.non_retryable is True
            assert "3" in str(exc_info.value)


@pytest.mark.django_db(transaction=True)
class TestEnsureSessionAssetActivity:
    @pytest.mark.asyncio
    async def test_creates_new_asset_with_vision_render_params(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        result = await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=scanner.team_id, session_id="sess-fresh")
        )
        assert isinstance(result, EnsureSessionAssetOutput)

        asset = await ExportedAsset.objects.aget(pk=result.asset_id)
        assert asset.team_id == scanner.team_id
        assert asset.export_format == "video/mp4"
        assert asset.is_system is True
        ctx = asset.export_context or {}
        assert ctx["session_recording_id"] == "sess-fresh"
        assert ctx["playback_speed"] == 8
        assert ctx["recording_fps"] == 3
        assert ctx["show_metadata_footer"] is True

    @pytest.mark.asyncio
    async def test_reuses_existing_system_asset_for_same_session(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        first = await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=scanner.team_id, session_id="sess-reuse")
        )
        second = await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=scanner.team_id, session_id="sess-reuse")
        )
        assert first.asset_id == second.asset_id

        @sync_to_async
        def _count() -> int:
            return ExportedAsset.objects.filter(
                team_id=scanner.team_id, export_context__session_recording_id="sess-reuse"
            ).count()

        assert await _count() == 1

    @pytest.mark.asyncio
    async def test_reuse_does_not_mutate_existing_asset(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        first = await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=scanner.team_id, session_id="sess-immutable")
        )

        # Simulate a previous rasterize run writing output fields onto the asset.
        @sync_to_async
        def _stamp_output() -> None:
            asset = ExportedAsset.objects.get(pk=first.asset_id)
            ctx = dict(asset.export_context or {})
            ctx["render_fingerprint"] = "abcdef"
            ctx["content_location"] = "s3://prior/video.mp4"
            asset.export_context = ctx
            asset.save(update_fields=["export_context"])

        await _stamp_output()

        await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=scanner.team_id, session_id="sess-immutable")
        )

        asset = await ExportedAsset.objects.aget(pk=first.asset_id)
        ctx = asset.export_context or {}
        assert ctx["render_fingerprint"] == "abcdef"
        assert ctx["content_location"] == "s3://prior/video.mp4"


class TestCleanupGeminiFileActivity:
    @pytest.mark.asyncio
    async def test_deletes_file_and_clears_tracking(self, gemini_redis) -> None:
        await gemini_redis.set(f"{_GEMINI_REDIS_KEY_PREFIX}files/rv-ok", "{}")
        await gemini_redis.zadd(_GEMINI_REDIS_INDEX_KEY, {"files/rv-ok": 0.0})
        fake_client = MagicMock()
        with patch(
            "products.replay_vision.backend.temporal.activities.cleanup_gemini_file.RawGenAIClient",
            return_value=fake_client,
        ):
            await cleanup_gemini_file_activity(CleanupGeminiFileInputs(gemini_file_name="files/rv-ok"))
        fake_client.files.delete.assert_called_once_with(name="files/rv-ok")
        assert await gemini_redis.exists(f"{_GEMINI_REDIS_KEY_PREFIX}files/rv-ok") == 0
        assert await gemini_redis.zscore(_GEMINI_REDIS_INDEX_KEY, "files/rv-ok") is None

    @pytest.mark.asyncio
    async def test_keeps_tracking_on_transient_failure(self, gemini_redis) -> None:
        await gemini_redis.set(f"{_GEMINI_REDIS_KEY_PREFIX}files/rv-transient", "{}")
        await gemini_redis.zadd(_GEMINI_REDIS_INDEX_KEY, {"files/rv-transient": 0.0})
        fake_client = MagicMock()
        fake_client.files.delete.side_effect = RuntimeError("gemini down")
        with patch(
            "products.replay_vision.backend.temporal.activities.cleanup_gemini_file.RawGenAIClient",
            return_value=fake_client,
        ):
            await cleanup_gemini_file_activity(CleanupGeminiFileInputs(gemini_file_name="files/rv-transient"))
        assert await gemini_redis.exists(f"{_GEMINI_REDIS_KEY_PREFIX}files/rv-transient") == 1
        assert await gemini_redis.zscore(_GEMINI_REDIS_INDEX_KEY, "files/rv-transient") is not None

    @pytest.mark.parametrize("code", [403, 404])
    @pytest.mark.asyncio
    async def test_clears_tracking_when_file_already_gone(self, gemini_redis, code: int) -> None:
        # Gemini reports missing files as 403 PERMISSION_DENIED ("...or it may not exist") or 404;
        # either way the file can't be deleted, so the tracking key must be dropped.
        await gemini_redis.set(f"{_GEMINI_REDIS_KEY_PREFIX}files/rv-gone", "{}")
        await gemini_redis.zadd(_GEMINI_REDIS_INDEX_KEY, {"files/rv-gone": 0.0})
        fake_client = MagicMock()
        fake_client.files.delete.side_effect = APIError(code=code, response_json={})
        with patch(
            "products.replay_vision.backend.temporal.activities.cleanup_gemini_file.RawGenAIClient",
            return_value=fake_client,
        ):
            await cleanup_gemini_file_activity(CleanupGeminiFileInputs(gemini_file_name="files/rv-gone"))
        assert await gemini_redis.exists(f"{_GEMINI_REDIS_KEY_PREFIX}files/rv-gone") == 0
        assert await gemini_redis.zscore(_GEMINI_REDIS_INDEX_KEY, "files/rv-gone") is None


def _build_inputs(**overrides: Any) -> ApplyScannerInputs:
    defaults: dict[str, Any] = {
        "scanner_id": uuid.uuid4(),
        "session_id": "sess-1",
        "team_id": 1,
        "triggered_by": ObservationTrigger.ON_DEMAND,
        "triggered_by_user_id": None,
    }
    defaults.update(overrides)
    return ApplyScannerInputs(**defaults)


class _WorkflowMocks:
    """Tracks `wf.execute_activity` and `wf.execute_child_workflow` calls and dispatches return values per activity."""

    def __init__(
        self,
        *,
        activity_results: dict[Any, Any] | None = None,
        activity_errors: dict[Any, Exception] | None = None,
    ) -> None:
        self.activity_results = activity_results or {}
        self.activity_errors = activity_errors or {}
        self.activity_calls: list[tuple[Any, Any]] = []
        self.child_calls: list[tuple[tuple, dict]] = []

    async def execute_activity(self, activity_fn: Any, activity_input: Any, **_: Any) -> Any:
        self.activity_calls.append((activity_fn, activity_input))
        if activity_fn in self.activity_errors:
            raise self.activity_errors[activity_fn]
        return self.activity_results.get(activity_fn)

    async def execute_child_workflow(self, *args: Any, **kwargs: Any) -> Any:
        self.child_calls.append((args, kwargs))
        return None


async def _run_workflow(inputs: ApplyScannerInputs, mocks: _WorkflowMocks, workflow_id: str = "wf-test") -> None:
    workflow_info = MagicMock()
    workflow_info.workflow_id = workflow_id
    with (
        patch("temporalio.workflow.info", return_value=workflow_info),
        patch("temporalio.workflow.execute_activity", side_effect=mocks.execute_activity),
        patch("temporalio.workflow.execute_child_workflow", side_effect=mocks.execute_child_workflow),
        # `wf.logger` requires a real workflow event loop, which this direct-call harness skips.
        patch("temporalio.workflow.logger"),
    ):
        await ApplyScannerWorkflow().run(inputs)


@pytest.mark.asyncio
async def test_apply_scanner_workflow_drives_full_success_pipeline() -> None:
    new_observation_id = uuid.uuid4()
    model_output = MonitorOutput(verdict="yes", reasoning="user exported", confidence=0.9)
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=new_observation_id, was_created=True, scanner_type=ScannerType.MONITOR
            ),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(model_output=model_output),
        },
    )

    inputs = _build_inputs(session_id="sess-1", team_id=99)
    await _run_workflow(inputs, mocks, workflow_id="wf-success")

    activity_order = [fn for fn, _ in mocks.activity_calls]
    assert activity_order[:2] == [create_observation_activity, mark_observation_running_activity]
    # fetch + ensure_asset run in parallel — order between them is non-deterministic.
    assert set(activity_order[2:4]) == {fetch_session_events_activity, ensure_session_asset_activity}
    # Success is persisted before any downstream emission so a late transient failure can't discard the result.
    assert activity_order[4:] == [
        upload_video_to_gemini_activity,
        call_scanner_provider_activity,
        mark_observation_succeeded_activity,
        emit_observation_event_activity,
        embed_observation_activity,
        cleanup_gemini_file_activity,
    ]
    assert len(mocks.child_calls) == 1
    assert mocks.child_calls[0][1]["id"] == f"replay-vision-rasterize-99-sess-1-{inputs.scanner_id}"

    emit_input = next(arg for fn, arg in mocks.activity_calls if fn is emit_observation_event_activity)
    assert emit_input.model_output == model_output
    cleanup_input = next(arg for fn, arg in mocks.activity_calls if fn is cleanup_gemini_file_activity)
    assert cleanup_input.gemini_file_name == "files/x"
    succeeded = next(arg for fn, arg in mocks.activity_calls if fn is mark_observation_succeeded_activity)
    assert succeeded.scanner_result.signals_count == 0


@pytest.mark.asyncio
async def test_apply_scanner_workflow_marks_failed_when_fetch_raises() -> None:
    new_observation_id = uuid.uuid4()
    fetch_error = ApplicationError("no events", non_retryable=True)
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=new_observation_id, was_created=True, scanner_type=ScannerType.MONITOR
            ),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
        },
        activity_errors={fetch_session_events_activity: fetch_error},
    )

    with pytest.raises(ApplicationError, match="no events"):
        await _run_workflow(_build_inputs(session_id="sess-broken"), mocks)

    called = {fn for fn, _ in mocks.activity_calls}
    assert create_observation_activity in called
    assert mark_observation_running_activity in called
    assert fetch_session_events_activity in called
    assert mark_observation_failed_activity in called
    assert mocks.child_calls == []

    failed_input = mocks.activity_calls[-1][1]
    assert failed_input.observation_id == new_observation_id
    assert "no events" in failed_input.error_reason.lower()


@pytest.mark.asyncio
async def test_apply_scanner_workflow_cleans_up_gemini_file_when_call_provider_fails() -> None:
    new_observation_id = uuid.uuid4()
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=new_observation_id, was_created=True, scanner_type=ScannerType.MONITOR
            ),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
        },
        activity_errors={call_scanner_provider_activity: ApplicationError("model rejected", non_retryable=True)},
    )

    with pytest.raises(ApplicationError, match="model rejected"):
        await _run_workflow(_build_inputs(session_id="sess-bad"), mocks)

    called = {fn for fn, _ in mocks.activity_calls}
    assert upload_video_to_gemini_activity in called
    assert call_scanner_provider_activity in called
    assert cleanup_gemini_file_activity in called  # cleanup ran despite call_provider raising
    assert mark_observation_failed_activity in called
    # mark_succeeded must NOT have been called
    assert mark_observation_succeeded_activity not in called


@pytest.mark.asyncio
async def test_apply_scanner_workflow_succeeds_even_when_cleanup_fails() -> None:
    # Cleanup is best-effort; a cleanup failure must not bring down an already-succeeded workflow.
    new_observation_id = uuid.uuid4()
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=new_observation_id, was_created=True, scanner_type=ScannerType.MONITOR
            ),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(
                model_output=MonitorOutput(verdict="yes", reasoning="ok", confidence=0.9),
            ),
        },
        activity_errors={cleanup_gemini_file_activity: RuntimeError("cleanup failed")},
    )

    # Workflow should complete without raising despite cleanup failure.
    await _run_workflow(_build_inputs(session_id="sess-ok"), mocks)

    called = {fn for fn, _ in mocks.activity_calls}
    assert mark_observation_succeeded_activity in called
    assert emit_observation_event_activity in called
    assert cleanup_gemini_file_activity in called


@pytest.mark.asyncio
async def test_apply_scanner_workflow_stays_succeeded_when_post_success_emissions_fail() -> None:
    # Once the result is persisted, event/embedding outages must not demote the observation to FAILED.
    new_observation_id = uuid.uuid4()
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=new_observation_id, was_created=True, scanner_type=ScannerType.MONITOR
            ),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(
                model_output=MonitorOutput(verdict="yes", reasoning="ok", confidence=0.9),
            ),
        },
        activity_errors={
            emit_observation_event_activity: RuntimeError("kafka down"),
            embed_observation_activity: RuntimeError("embedding service down"),
        },
    )

    await _run_workflow(_build_inputs(session_id="sess-flaky"), mocks)

    called = {fn for fn, _ in mocks.activity_calls}
    assert mark_observation_succeeded_activity in called
    assert emit_observation_event_activity in called
    assert embed_observation_activity in called
    assert mark_observation_failed_activity not in called


@pytest.mark.asyncio
async def test_apply_scanner_workflow_marks_failed_when_mark_running_fails() -> None:
    # An exhausted mark_running must land the row in FAILED, not strand it in PENDING.
    new_observation_id = uuid.uuid4()
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=new_observation_id, was_created=True, scanner_type=ScannerType.MONITOR
            ),
        },
        activity_errors={mark_observation_running_activity: ApplicationError("db down", non_retryable=True)},
    )

    with pytest.raises(ApplicationError, match="db down"):
        await _run_workflow(_build_inputs(session_id="sess-db-down"), mocks)

    failed_input = next(arg for fn, arg in mocks.activity_calls if fn is mark_observation_failed_activity)
    assert failed_input.observation_id == new_observation_id


@pytest.mark.asyncio
async def test_apply_scanner_workflow_exits_when_create_returns_was_created_false() -> None:
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=uuid.uuid4(), was_created=False, scanner_type=ScannerType.MONITOR
            ),
        },
    )

    await _run_workflow(_build_inputs(session_id="sess-dup"), mocks)

    assert [fn for fn, _ in mocks.activity_calls] == [create_observation_activity]
    assert mocks.child_calls == []


def test_workflow_get_progress_advances_through_phases() -> None:
    workflow = ApplyScannerWorkflow()
    assert workflow.get_progress() == {
        "phase": "queued",
        "step": 0,
        "total_steps": 6,
        "rasterizer_workflow_id": None,
    }

    workflow._advance_phase("rendering", rasterizer_workflow_id="rast-1")
    progress = workflow.get_progress()
    assert progress["phase"] == "rendering"
    assert progress["step"] == 2
    assert progress["rasterizer_workflow_id"] == "rast-1"

    # A later phase without an id keeps the previously recorded rasterizer id.
    workflow._advance_phase("analyzing")
    assert workflow.get_progress()["phase"] == "analyzing"
    assert workflow.get_progress()["rasterizer_workflow_id"] == "rast-1"


async def test_progress_stream_completes_immediately_for_terminal_observation() -> None:
    # Fast path: opening the stream for a settled observation emits a single complete event and closes.
    observation = ReplayObservation(id=uuid.uuid4(), status=ObservationStatus.SUCCEEDED)
    events = [event async for event in stream_observation_progress(observation)]
    assert len(events) == 1
    assert "event: observation-complete" in events[0]
    assert '"status": "succeeded"' in events[0]


@pytest.mark.asyncio
async def test_apply_scanner_workflow_propagates_workflow_id_to_create() -> None:
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=uuid.uuid4(), was_created=False, scanner_type=ScannerType.MONITOR
            ),
        },
    )
    inputs = _build_inputs(
        scanner_id=uuid.uuid4(),
        session_id="sess-id",
        team_id=7,
        triggered_by=ObservationTrigger.SCHEDULE,
        triggered_by_user_id=42,
    )

    await _run_workflow(inputs, mocks, workflow_id="wf-from-info")

    create_input = mocks.activity_calls[0][1]
    assert create_input.scanner_id == inputs.scanner_id
    assert create_input.session_id == "sess-id"
    assert create_input.team_id == 7
    assert create_input.triggered_by == ObservationTrigger.SCHEDULE
    assert create_input.triggered_by_user_id == 42
    assert create_input.workflow_id == "wf-from-info"


def _summarizer_output_with_facets() -> SummarizerOutput:
    return SummarizerOutput(
        title="Login attempt",
        summary="User tried to authenticate but the form failed twice.",
        intent="Log in to the dashboard",
        outcome="Reached the password reset page after failed attempts.",
        friction_points=["invalid password error"],
        keywords=["login", "authentication", "reset"],
        confidence=0.9,
    )


def _summarizer_output_without_facets() -> SummarizerOutput:
    return SummarizerOutput(title="Onboarding", summary="User walked through the demo.", confidence=0.9)


def _classifier_output() -> ClassifierOutput:
    return ClassifierOutput(
        tags=["support"],
        tags_freeform=["billing"],
        reasoning="user contacted support about billing",
        confidence=0.85,
    )


@pytest.mark.asyncio
async def test_embed_observation_emits_one_request_per_nonempty_facet() -> None:
    out = SummarizerOutput(
        title="Investigation",
        summary="User browsed dashboards and clicked through several insights.",
        intent="Investigate slow query response",
        outcome="No issue reproduced — user closed the tab.",
        friction_points=[],
        keywords=["dashboard", "insight"],
        confidence=0.8,
    )
    scanner_id = uuid.uuid4()
    inputs = EmbedObservationInputs(
        team_id=99, session_id="sess-abc", observation_id=uuid.uuid4(), scanner_id=scanner_id, model_output=out
    )
    with patch(
        "products.replay_vision.backend.temporal.activities.embed_observation.emit_embedding_request"
    ) as mock_emit:
        await embed_observation_activity(inputs)

    renderings = [call.kwargs["rendering"] for call in mock_emit.call_args_list]
    assert renderings == ["intent", "outcome", "keywords"]
    for call in mock_emit.call_args_list:
        assert call.kwargs["team_id"] == 99
        assert call.kwargs["product"] == "replay-vision"
        assert call.kwargs["document_type"] == "replay-observation"
        assert call.kwargs["document_id"] == str(inputs.observation_id)
        assert call.kwargs["models"] == ["text-embedding-3-large-3072"]
        # session_id + scanner_id are carried in metadata so search results map embeddings → sessions, scoped to a scanner.
        assert call.kwargs["metadata"]["session_id"] == "sess-abc"
        assert call.kwargs["metadata"]["team_id"] == 99
        assert call.kwargs["metadata"]["observation_id"] == str(inputs.observation_id)
        assert call.kwargs["metadata"]["scanner_id"] == str(scanner_id)


@parameterized.expand(
    [
        (
            "monitor",
            MonitorOutput(verdict="no", reasoning="checkout button never rendered", confidence=0.9),
            {"verdict": "no"},
        ),
        (
            "scorer",
            ScorerOutput(score=0.0, reasoning="user rage-clicked a broken button", confidence=0.7),
            {"score": 0.0},
        ),
        ("classifier", _classifier_output(), {"tags": ["support", "billing"]}),
    ]
)
@pytest.mark.asyncio
async def test_embed_observation_emits_reasoning_for_non_summarizer(_name, model_output, expected_metadata) -> None:
    scanner_id = uuid.uuid4()
    inputs = EmbedObservationInputs(
        team_id=99, session_id="sess-r", observation_id=uuid.uuid4(), scanner_id=scanner_id, model_output=model_output
    )
    with patch(
        "products.replay_vision.backend.temporal.activities.embed_observation.emit_embedding_request"
    ) as mock_emit:
        await embed_observation_activity(inputs)

    assert [call.kwargs["rendering"] for call in mock_emit.call_args_list] == ["reasoning"]
    call = mock_emit.call_args_list[0]
    assert call.kwargs["content"] == model_output.reasoning
    assert call.kwargs["document_id"] == str(inputs.observation_id)
    metadata = call.kwargs["metadata"]
    assert metadata["scanner_id"] == str(scanner_id)
    # The exact outcome is stamped into metadata so search can filter on it inside ClickHouse.
    for key, value in expected_metadata.items():
        assert metadata[key] == value


@pytest.mark.asyncio
async def test_embed_observation_raises_propagates_failure() -> None:
    inputs = EmbedObservationInputs(
        team_id=99,
        session_id="sess-x",
        observation_id=uuid.uuid4(),
        scanner_id=uuid.uuid4(),
        model_output=_summarizer_output_with_facets(),
    )
    with patch(
        "products.replay_vision.backend.temporal.activities.embed_observation.emit_embedding_request",
        side_effect=RuntimeError("kafka down"),
    ):
        with pytest.raises(RuntimeError, match="kafka down"):
            await embed_observation_activity(inputs)


@pytest.mark.asyncio
async def test_emit_classifier_tags_produces_kafka_payload() -> None:
    inputs = EmitClassifierTagsInputs(
        team_id=99, session_id="sess-classify", observation_id=uuid.uuid4(), classifier_output=_classifier_output()
    )
    session_start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)

    with (
        patch(
            "products.replay_vision.backend.temporal.activities.emit_classifier_tags._load_session_identity",
            return_value=("user-77", session_start),
        ),
        patch(
            "products.replay_vision.backend.temporal.activities.emit_classifier_tags.producer_scope"
        ) as mock_producer_scope,
    ):
        producer = mock_producer_scope.return_value.__enter__.return_value

        await emit_classifier_tags_activity(inputs)

    producer.produce.assert_called_once()
    payload = producer.produce.call_args.kwargs["data"]
    assert payload["session_id"] == "sess-classify"
    assert payload["team_id"] == 99
    assert payload["distinct_id"] == "user-77"
    assert payload["ai_tags_fixed"] == ["support"]
    assert payload["ai_tags_freeform"] == ["billing"]
    assert "ai_highlighted" not in payload
    assert payload["click_count"] == 0
    assert payload["keypress_count"] == 0
    assert payload["urls"] == []
    assert payload["first_url"] is None


@pytest.mark.asyncio
async def test_emit_classifier_tags_raises_when_metadata_missing() -> None:
    inputs = EmitClassifierTagsInputs(
        team_id=99, session_id="sess-missing", observation_id=uuid.uuid4(), classifier_output=_classifier_output()
    )
    with patch(
        "products.replay_vision.backend.temporal.activities.emit_classifier_tags._load_session_identity",
        return_value=None,
    ):
        with pytest.raises(ApplicationError, match="No persisted session metadata"):
            await emit_classifier_tags_activity(inputs)


@pytest.mark.asyncio
async def test_embed_observation_raises_when_kafka_delivery_fails() -> None:
    inputs = EmbedObservationInputs(
        team_id=99,
        session_id="sess-x",
        observation_id=uuid.uuid4(),
        scanner_id=uuid.uuid4(),
        model_output=_summarizer_output_with_facets(),
    )
    failed_result = MagicMock()
    failed_result.get.side_effect = RuntimeError("broker timeout")
    with patch(
        "products.replay_vision.backend.temporal.activities.embed_observation.emit_embedding_request",
        return_value=failed_result,
    ):
        with pytest.raises(RuntimeError, match="broker timeout"):
            await embed_observation_activity(inputs)


@pytest.mark.asyncio
async def test_emit_classifier_tags_raises_when_kafka_delivery_fails() -> None:
    inputs = EmitClassifierTagsInputs(
        team_id=99, session_id="sess-classify", observation_id=uuid.uuid4(), classifier_output=_classifier_output()
    )
    session_start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
    failed_result = MagicMock()
    failed_result.get.side_effect = RuntimeError("broker timeout")

    with (
        patch(
            "products.replay_vision.backend.temporal.activities.emit_classifier_tags._load_session_identity",
            return_value=("user-77", session_start),
        ),
        patch(
            "products.replay_vision.backend.temporal.activities.emit_classifier_tags.producer_scope"
        ) as mock_producer_scope,
    ):
        producer = mock_producer_scope.return_value.__enter__.return_value
        producer.produce.return_value = failed_result

        with pytest.raises(RuntimeError, match="broker timeout"):
            await emit_classifier_tags_activity(inputs)


@pytest.mark.asyncio
async def test_apply_scanner_workflow_dispatches_summarizer_embedding_when_facets_present() -> None:
    new_observation_id = uuid.uuid4()
    model_output = _summarizer_output_with_facets()
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=new_observation_id,
                was_created=True,
                scanner_type=ScannerType.SUMMARIZER,
            ),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(model_output=model_output),
        },
    )

    await _run_workflow(_build_inputs(session_id="sess-sum", team_id=99), mocks, workflow_id="wf-sum")

    activity_order = [fn for fn, _ in mocks.activity_calls]
    call_idx = activity_order.index(call_scanner_provider_activity)
    assert activity_order[call_idx + 1] == mark_observation_succeeded_activity
    assert activity_order[call_idx + 2] == emit_observation_event_activity
    assert activity_order[call_idx + 3] == embed_observation_activity
    assert emit_classifier_tags_activity not in activity_order

    embed_input = next(arg for fn, arg in mocks.activity_calls if fn is embed_observation_activity)
    assert embed_input.session_id == "sess-sum"
    assert embed_input.team_id == 99
    assert embed_input.model_output == model_output


@pytest.mark.asyncio
async def test_apply_scanner_workflow_skips_summarizer_embedding_when_no_facets() -> None:
    new_observation_id = uuid.uuid4()
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=new_observation_id,
                was_created=True,
                scanner_type=ScannerType.SUMMARIZER,
            ),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(model_output=_summarizer_output_without_facets()),
        },
    )

    await _run_workflow(_build_inputs(session_id="sess-nofacets"), mocks)

    called = {fn for fn, _ in mocks.activity_calls}
    assert embed_observation_activity not in called


@pytest.mark.asyncio
async def test_apply_scanner_workflow_dispatches_classifier_side_effect() -> None:
    new_observation_id = uuid.uuid4()
    model_output = _classifier_output()
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=new_observation_id, was_created=True, scanner_type=ScannerType.MONITOR
            ),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(model_output=model_output),
        },
    )

    await _run_workflow(_build_inputs(session_id="sess-cls", team_id=99), mocks, workflow_id="wf-cls")

    # Classifiers embed their reasoning AND fan out tags; both run after success is persisted, embedding first.
    activity_order = [fn for fn, _ in mocks.activity_calls]
    call_idx = activity_order.index(call_scanner_provider_activity)
    assert activity_order[call_idx + 1] == mark_observation_succeeded_activity
    assert activity_order[call_idx + 2] == emit_observation_event_activity
    assert activity_order[call_idx + 3] == embed_observation_activity
    assert activity_order[call_idx + 4] == emit_classifier_tags_activity

    embed_input = next(arg for fn, arg in mocks.activity_calls if fn is embed_observation_activity)
    assert embed_input.model_output == model_output
    tag_input = next(arg for fn, arg in mocks.activity_calls if fn is emit_classifier_tags_activity)
    assert tag_input.classifier_output == model_output


@pytest.mark.asyncio
async def test_apply_scanner_workflow_embeds_monitor_reasoning_without_classifier_tags() -> None:
    new_observation_id = uuid.uuid4()
    model_output = MonitorOutput(verdict="yes", reasoning="user exported", confidence=0.9)
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=new_observation_id, was_created=True, scanner_type=ScannerType.MONITOR
            ),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(model_output=model_output),
        },
    )

    await _run_workflow(_build_inputs(session_id="sess-mon", team_id=99), mocks, workflow_id="wf-mon")

    called = {fn for fn, _ in mocks.activity_calls}
    # Monitors carry a `reasoning` paragraph, so the embedding side-effect runs; only classifiers fan out tags.
    assert embed_observation_activity in called
    assert emit_classifier_tags_activity not in called

    embed_input = next(arg for fn, arg in mocks.activity_calls if fn is embed_observation_activity)
    assert embed_input.model_output == model_output


def _wrap_in_activity_error(cause: ApplicationError) -> ActivityError:
    """Build a minimal ActivityError shaped like what Temporal raises into a workflow's `except` block."""
    activity_err = ActivityError.__new__(ActivityError)
    activity_err.__cause__ = cause
    return activity_err


class TestWorkflowErrorHelpers:
    """Unit tests for the workflow's exception-classification helpers."""

    def test_extract_ineligible_kind_returns_kind_for_direct_ineligible_session_error(self) -> None:
        err = IneligibleSessionError("session is too short", kind=IneligibleSessionKind.TOO_SHORT)
        assert _extract_kind_for_type(err, INELIGIBLE_SESSION_ERROR_TYPE) == "too_short"

    def test_extract_ineligible_kind_unwraps_activity_error_from_worker(self) -> None:
        leaf = IneligibleSessionError("no recording", kind=IneligibleSessionKind.NO_RECORDING)
        wrapped = _wrap_in_activity_error(leaf)
        assert _extract_kind_for_type(wrapped, INELIGIBLE_SESSION_ERROR_TYPE) == "no_recording"

    def test_extract_ineligible_kind_returns_none_for_unrelated_application_error(self) -> None:
        err = ApplicationError("something broke", type="RuntimeError", non_retryable=True)
        assert _extract_kind_for_type(err, INELIGIBLE_SESSION_ERROR_TYPE) is None

    def test_extract_failure_kind_returns_kind_for_scanner_failure_error(self) -> None:
        err = ScannerFailureError("gemini rejected", kind=FailureKind.PROVIDER_REJECTED)
        assert _extract_kind_for_type(err, SCANNER_FAILURE_ERROR_TYPE) == "provider_rejected"

    def test_extract_failure_kind_unwraps_activity_error_from_worker(self) -> None:
        leaf = ScannerFailureError("missing asset", kind=FailureKind.INTERNAL_ERROR)
        wrapped = _wrap_in_activity_error(leaf)
        assert _extract_kind_for_type(wrapped, SCANNER_FAILURE_ERROR_TYPE) == "internal_error"

    def test_extract_failure_kind_returns_none_for_unrelated_application_error(self) -> None:
        err = ApplicationError("something broke", type="RuntimeError", non_retryable=True)
        assert _extract_kind_for_type(err, SCANNER_FAILURE_ERROR_TYPE) is None

    def test_root_cause_message_strips_temporal_wrapper(self) -> None:
        leaf = ApplicationError("Gemini file files/abc reached state FAILED", type="RuntimeError")
        wrapped = _wrap_in_activity_error(leaf)
        assert _root_cause_message(wrapped) == "Gemini file files/abc reached state FAILED"

    def test_root_cause_message_falls_back_to_str_for_bare_exceptions(self) -> None:
        assert _root_cause_message(ValueError("bad arg")) == "bad arg"

    @parameterized.expand(
        [
            ("provider_call_timeout", "call_scanner_provider_activity", True, "provider_transient"),
            ("upload_timeout", "replay_vision_upload_video_to_gemini_activity", True, "provider_transient"),
            ("other_activity_timeout", "replay_vision_fetch_session_events_activity", True, None),
            ("provider_call_non_timeout", "call_scanner_provider_activity", False, None),
        ]
    )
    def test_activity_timeout_kind_maps_provider_activity_timeouts(
        self, _label: str, activity_type: str, timed_out: bool, expected: str | None
    ) -> None:
        err = ActivityError(
            "activity failed",
            scheduled_event_id=1,
            started_event_id=2,
            identity="worker",
            activity_type=activity_type,
            activity_id="a1",
            retry_state=None,
        )
        if timed_out:
            err.__cause__ = TemporalTimeoutError(
                "timed out", type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[]
            )
        else:
            err.__cause__ = ApplicationError("boom", type="RuntimeError")
        assert _activity_timeout_kind(err) == expected


_DURATION_MS = 600_000  # 10-minute recording for the citation tests


def _monitor_scanner() -> MonitorScanner:
    return MonitorScanner(prompt="p")


def _summarizer_scanner() -> SummarizerScanner:
    return SummarizerScanner(prompt="p")


class TestExtractSegments:
    @pytest.mark.parametrize(
        "text,expected_plain,expected_segments",
        [
            pytest.param(
                "Foo (t 12) bar",
                "Foo bar",
                [TextSegment(value="Foo"), ChipSegment(timestamp_ms=12_000), TextSegment(value=" bar")],
                id="inline",
            ),
            pytest.param(
                "A (t 1) then B (t 5) then C.",
                "A then B then C.",
                [
                    TextSegment(value="A"),
                    ChipSegment(timestamp_ms=1_000),
                    TextSegment(value=" then B"),
                    ChipSegment(timestamp_ms=5_000),
                    TextSegment(value=" then C."),
                ],
                id="multiple",
            ),
            pytest.param(
                "X (t 50) Y (t 99999) Z.",
                "X Y Z.",
                [
                    TextSegment(value="X"),
                    ChipSegment(timestamp_ms=50_000),
                    TextSegment(value=" Y"),
                    TextSegment(value=" Z."),
                ],
                id="out_of_range_dropped",
            ),
            pytest.param(
                "(t 0) was the cause.",
                " was the cause.",
                [ChipSegment(timestamp_ms=0), TextSegment(value=" was the cause.")],
                id="citation_at_start",
            ),
            pytest.param(
                "It ended (t 30)",
                "It ended",
                [TextSegment(value="It ended"), ChipSegment(timestamp_ms=30_000)],
                id="citation_at_end",
            ),
            pytest.param(
                "Nothing to strip.",
                "Nothing to strip.",
                [TextSegment(value="Nothing to strip.")],
                id="no_citations",
            ),
        ],
    )
    def test_extract_segments(self, text: str, expected_plain: str, expected_segments: list[Segment]) -> None:
        plain, segments = _extract_segments(text, _DURATION_MS)
        assert plain == expected_plain
        assert segments == expected_segments


class TestResolveCitations:
    def test_populates_field_and_segments(self) -> None:
        finalized = MonitorOutput(verdict="yes", reasoning="User retried (t 12) twice.", confidence=0.9)
        resolved = _resolve_citations(finalized, _monitor_scanner(), _DURATION_MS)
        assert isinstance(resolved, MonitorOutput)
        assert resolved.reasoning == "User retried twice."
        assert resolved.reasoning_segments == [
            TextSegment(value="User retried"),
            ChipSegment(timestamp_ms=12_000),
            TextSegment(value=" twice."),
        ]

    def test_summarizer_uses_summary_field(self) -> None:
        finalized = SummarizerOutput(title="t", summary="They tried X (t 7).", confidence=0.9)
        resolved = _resolve_citations(finalized, _summarizer_scanner(), _DURATION_MS)
        assert isinstance(resolved, SummarizerOutput)
        assert resolved.summary == "They tried X."
        assert any(isinstance(s, ChipSegment) and s.timestamp_ms == 7_000 for s in resolved.summary_segments)

    def test_no_citations_in_text_yields_single_text_segment(self) -> None:
        finalized = MonitorOutput(verdict="yes", reasoning="No citations here.", confidence=0.9)
        resolved = _resolve_citations(finalized, _monitor_scanner(), _DURATION_MS)
        assert isinstance(resolved, MonitorOutput)
        assert resolved.reasoning == "No citations here."
        assert resolved.reasoning_segments == [TextSegment(value="No citations here.")]


# emit_observation_signal_activity

_EMIT_SIGNAL_PATCH = "products.replay_vision.backend.temporal.activities.emit_observation_signal.emit_signal"
_LOAD_LLM_INPUTS_PATCH = "products.replay_vision.backend.temporal.activities.emit_observation_signal._load_llm_inputs"


@pytest.mark.django_db(transaction=True)
class TestEmitObservationSignalActivity:
    def _signal(self, confidence: float = 0.8, **overrides) -> SignalFinding:
        defaults: dict = {
            "problem_type": "bug",
            "start_time": 72,
            "end_time": 78,
            "url": "https://app.example.com/cart",
            "description": "Broken checkout CTA on /cart",
            "confidence": confidence,
        }
        defaults.update(overrides)
        return SignalFinding(**defaults)

    def _inputs(
        self,
        observation: ReplayObservation,
        confidence: float = 0.8,
        signals: list[SignalFinding] | None = None,
        **overrides,
    ) -> EmitObservationSignalInputs:
        defaults: dict = {
            "team_id": observation.team_id,
            "observation_id": observation.id,
            "exported_asset_id": 4242,
            "signals": signals if signals is not None else [self._signal(confidence)],
        }
        defaults.update(overrides)
        return EmitObservationSignalInputs(**defaults)

    def _llm_inputs(self, observation: ReplayObservation) -> ScannerLlmInputs:
        return ScannerLlmInputs(
            session_id=observation.session_id,
            team_id=observation.team_id,
            events=EventTable(columns=["event"], rows=[["$pageview"]]),
            distinct_id="user-distinct-99",
            metadata=SessionMetadata(
                start_time=dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC),
                end_time=dt.datetime(2026, 5, 12, 10, 5, 0, tzinfo=dt.UTC),
                duration_seconds=300.0,
                active_seconds=120.0,
            ),
        )

    def test_emits_via_the_signals_facade(self) -> None:
        scanner = _make_scanner(emits_signals=True)
        observation = _make_observation(scanner)

        with (
            patch(_EMIT_SIGNAL_PATCH, new_callable=AsyncMock) as mock_emit,
            patch(_LOAD_LLM_INPUTS_PATCH, return_value=self._llm_inputs(observation)),
        ):
            assert emit_observation_signal_activity(self._inputs(observation)) == 1

        assert mock_emit.await_args is not None
        kwargs = mock_emit.await_args.kwargs
        assert kwargs["source_product"] == "replay_vision"
        assert kwargs["source_type"] == "scanner_finding"
        assert kwargs["source_id"] == f"observation:{observation.id}:0"  # unique per finding (index 0)
        assert kwargs["description"] == "Broken checkout CTA on /cart"
        assert kwargs["weight"] == SIGNAL_WEIGHT
        extra = kwargs["extra"]
        assert extra["scanner_id"] == str(scanner.id)
        assert extra["scanner_type"] == "monitor"
        assert extra["session_id"] == observation.session_id
        assert extra["confidence"] == 0.8
        # Stolen from the session-summaries signal shape:
        assert extra["problem_type"] == "bug"
        assert extra["start_time"] == 72
        assert extra["end_time"] == 78
        assert extra["url"] == "https://app.example.com/cart"
        assert extra["exported_asset_id"] == 4242
        assert extra["distinct_id"] == "user-distinct-99"
        # These are the *recording* (snapshot) bounds — the REC_T=0 anchor for start_time/end_time.
        assert extra["recording_start_time"] == "2026-05-12T10:00:00+00:00"
        assert extra["recording_end_time"] == "2026-05-12T10:05:00+00:00"
        assert extra["recording_duration"] == 300.0
        assert extra["recording_active_seconds"] == 120.0

        # The variant is `extra="forbid"`: every emitted key must be declared, or the facade silently
        # drops the signal (fail-soft to 0). Validate the real payload to pin that contract.
        ReplayVisionScannerFindingSignalInput.model_validate(
            {
                "source_product": kwargs["source_product"],
                "source_type": kwargs["source_type"],
                "source_id": kwargs["source_id"],
                "description": kwargs["description"],
                "weight": kwargs["weight"],
                "extra": extra,
            }
        )

    def test_emits_without_session_metadata_when_redis_lapsed(self) -> None:
        # `_load_llm_inputs` returns None if the Redis state expired; emission still succeeds, session fields omitted.
        scanner = _make_scanner(emits_signals=True)
        observation = _make_observation(scanner)

        with (
            patch(_EMIT_SIGNAL_PATCH, new_callable=AsyncMock) as mock_emit,
            patch(_LOAD_LLM_INPUTS_PATCH, return_value=None),
        ):
            assert emit_observation_signal_activity(self._inputs(observation)) == 1

        assert mock_emit.await_args is not None
        extra = mock_emit.await_args.kwargs["extra"]
        assert extra["problem_type"] == "bug"
        assert "recording_start_time" not in extra
        assert "distinct_id" not in extra

    def test_enrichment_failure_does_not_drop_signals(self) -> None:
        # A Redis error fetching enrichment (vs. a clean None) must degrade to no-enrichment, not no-emission.
        scanner = _make_scanner(emits_signals=True)
        observation = _make_observation(scanner)

        with (
            patch(_EMIT_SIGNAL_PATCH, new_callable=AsyncMock) as mock_emit,
            patch(_LOAD_LLM_INPUTS_PATCH, side_effect=Exception("redis down")),
        ):
            assert emit_observation_signal_activity(self._inputs(observation)) == 1

        assert mock_emit.await_args is not None
        extra = mock_emit.await_args.kwargs["extra"]
        assert extra["problem_type"] == "bug"
        assert "recording_start_time" not in extra
        assert "distinct_id" not in extra

    def test_emits_one_signal_per_finding_with_unique_source_ids(self) -> None:
        scanner = _make_scanner(emits_signals=True)
        observation = _make_observation(scanner)
        signals = [self._signal(url="/one"), self._signal(url="/two"), self._signal(confidence=0.2, url="/low")]

        with (
            patch(_EMIT_SIGNAL_PATCH, new_callable=AsyncMock) as mock_emit,
            patch(_LOAD_LLM_INPUTS_PATCH, return_value=None),
        ):
            # Two emitted; the 0.2-confidence finding is below the floor and skipped.
            assert emit_observation_signal_activity(self._inputs(observation, signals=signals)) == 2

        calls = mock_emit.await_args_list
        assert [c.kwargs["source_id"] for c in calls] == [
            f"observation:{observation.id}:0",
            f"observation:{observation.id}:1",
        ]
        assert [c.kwargs["extra"]["url"] for c in calls] == ["/one", "/two"]

    @pytest.mark.parametrize("confidence", [0.0, 0.39])
    def test_skips_findings_below_the_confidence_floor(self, confidence: float) -> None:
        scanner = _make_scanner(emits_signals=True)
        observation = _make_observation(scanner)

        with patch(_EMIT_SIGNAL_PATCH, new_callable=AsyncMock) as mock_emit:
            assert emit_observation_signal_activity(self._inputs(observation, confidence=confidence)) == 0
        mock_emit.assert_not_awaited()

    def test_skips_when_the_snapshot_does_not_emit_signals(self) -> None:
        scanner = _make_scanner(emits_signals=False)
        observation = _make_observation(scanner)

        with patch(_EMIT_SIGNAL_PATCH, new_callable=AsyncMock) as mock_emit:
            assert emit_observation_signal_activity(self._inputs(observation)) == 0
        mock_emit.assert_not_awaited()

    def test_skips_when_the_observation_is_missing(self) -> None:
        scanner = _make_scanner(emits_signals=True)
        observation = _make_observation(scanner)
        inputs = self._inputs(observation, observation_id=uuid.uuid4())

        with patch(_EMIT_SIGNAL_PATCH, new_callable=AsyncMock) as mock_emit:
            assert emit_observation_signal_activity(inputs) == 0
        mock_emit.assert_not_awaited()

    @pytest.mark.parametrize(
        "error",
        [RuntimeError("signals down"), ValueError("description exceeds the token limit")],
        ids=["facade_down", "description_over_token_cap"],
    )
    def test_fails_soft_when_the_facade_raises(self, error: Exception) -> None:
        scanner = _make_scanner(emits_signals=True)
        observation = _make_observation(scanner)

        with patch(_EMIT_SIGNAL_PATCH, new_callable=AsyncMock, side_effect=error) as mock_emit:
            assert emit_observation_signal_activity(self._inputs(observation)) == 0
        mock_emit.assert_awaited_once()

    def test_emits_without_any_source_config(self) -> None:
        # Scanner findings are self-authorizing via the snapshot flag — no SignalSourceConfig is read or written.
        scanner = _make_scanner(emits_signals=True)
        observation = _make_observation(scanner)

        with patch(_EMIT_SIGNAL_PATCH, new_callable=AsyncMock) as mock_emit:
            assert emit_observation_signal_activity(self._inputs(observation)) == 1

        mock_emit.assert_awaited_once()
        assert not SignalSourceConfig.objects.filter(team=scanner.team).exists()


@pytest.mark.asyncio
async def test_apply_scanner_workflow_emits_the_signal_finding() -> None:
    new_observation_id = uuid.uuid4()
    model_output = MonitorOutput(verdict="yes", reasoning="user hit the broken CTA", confidence=0.9)
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=new_observation_id, was_created=True, scanner_type=ScannerType.MONITOR
            ),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(
                model_output=model_output,
                signals=[
                    SignalFinding(
                        problem_type="bug",
                        start_time=30,
                        end_time=35,
                        url="https://app.example.com/cart",
                        description="Checkout CTA is broken on /cart",
                        confidence=0.8,
                    )
                ],
            ),
            emit_observation_signal_activity: 1,
        },
    )

    await _run_workflow(_build_inputs(session_id="sess-sig", team_id=99), mocks)

    order = [fn for fn, _ in mocks.activity_calls]
    assert order.index(call_scanner_provider_activity) < order.index(emit_observation_signal_activity)
    assert order.index(emit_observation_signal_activity) < order.index(emit_observation_event_activity)

    signal_input = next(arg for fn, arg in mocks.activity_calls if fn is emit_observation_signal_activity)
    assert signal_input.observation_id == new_observation_id
    assert signal_input.exported_asset_id == 42  # threaded from ensure_session_asset_activity
    assert signal_input.signals[0].description == "Checkout CTA is broken on /cart"
    assert signal_input.signals[0].confidence == 0.8

    succeeded = next(arg for fn, arg in mocks.activity_calls if fn is mark_observation_succeeded_activity)
    assert succeeded.scanner_result.signals_count == 1


@pytest.mark.asyncio
async def test_apply_scanner_workflow_succeeds_when_the_signal_activity_fails() -> None:
    new_observation_id = uuid.uuid4()
    model_output = MonitorOutput(verdict="yes", reasoning="user hit the broken CTA", confidence=0.9)
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(
                observation_id=new_observation_id, was_created=True, scanner_type=ScannerType.MONITOR
            ),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(
                model_output=model_output,
                signals=[
                    SignalFinding(
                        problem_type="bug",
                        start_time=30,
                        end_time=35,
                        url="https://app.example.com/cart",
                        description="Checkout CTA is broken on /cart",
                        confidence=0.8,
                    )
                ],
            ),
        },
        activity_errors={emit_observation_signal_activity: TimeoutError("start-to-close exceeded")},
    )

    await _run_workflow(_build_inputs(session_id="sess-sig-fail", team_id=99), mocks)

    called = [fn for fn, _ in mocks.activity_calls]
    assert mark_observation_failed_activity not in called
    succeeded = next(arg for fn, arg in mocks.activity_calls if fn is mark_observation_succeeded_activity)
    assert succeeded.scanner_result.signals_count == 0
