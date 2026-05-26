import uuid
import datetime as dt
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

import psycopg.errors
from asgiref.sync import sync_to_async
from temporalio.exceptions import ApplicationError

from posthog.models import Organization, Team
from posthog.models.exported_asset import ExportedAsset
from posthog.models.user import User
from posthog.redis import get_async_client
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.temporal import ApplyScannerWorkflow
from products.replay_vision.backend.temporal.activities.call_scanner_provider import call_scanner_provider_activity
from products.replay_vision.backend.temporal.activities.cleanup_gemini_file import cleanup_gemini_file_activity
from products.replay_vision.backend.temporal.activities.create_observation import create_observation_activity
from products.replay_vision.backend.temporal.activities.embed_indexer_observation import (
    embed_indexer_observation_activity,
)
from products.replay_vision.backend.temporal.activities.emit_classifier_tags import emit_classifier_tags_activity
from products.replay_vision.backend.temporal.activities.emit_observation_event import emit_observation_event_activity
from products.replay_vision.backend.temporal.activities.ensure_session_asset import ensure_session_asset_activity
from products.replay_vision.backend.temporal.activities.fetch_session_events import fetch_session_events_activity
from products.replay_vision.backend.temporal.activities.observation_state import (
    mark_observation_failed_activity,
    mark_observation_running_activity,
    mark_observation_succeeded_activity,
)
from products.replay_vision.backend.temporal.activities.upload_video_to_gemini import upload_video_to_gemini_activity
from products.replay_vision.backend.temporal.scanners.classifier import ClassifierOutput
from products.replay_vision.backend.temporal.scanners.indexer import IndexerOutput
from products.replay_vision.backend.temporal.scanners.monitor import MonitorOutput
from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    generate_state_key,
    get_data_class_from_redis,
    store_data_in_redis,
)
from products.replay_vision.backend.temporal.types import (
    ApplyScannerInputs,
    CreateObservationInputs,
    CreateObservationOutput,
    EmbedIndexerObservationInputs,
    EmitClassifierTagsInputs,
    EnsureSessionAssetInputs,
    EnsureSessionAssetOutput,
    EventTable,
    FetchSessionEventsInputs,
    MarkObservationFailedInputs,
    MarkObservationRunningInputs,
    MarkObservationSucceededInputs,
    ScannerCallOutput,
    ScannerLlmInputs,
    ScannerResult,
    SessionMetadata,
    UploadedVideo,
)
from products.replay_vision.backend.tests.helpers import snapshot_for as _snapshot_for


def _make_scanner() -> ReplayScanner:
    org = Organization.objects.create(name="vision-test-org")
    team = Team.objects.create(organization=org, name="vision-test-team")
    return ReplayScanner.objects.create(
        team=team,
        name="t",
        scanner_type=ScannerType.MONITOR,
        scanner_config={"prompt": "p"},
        model=ScannerModel.GEMINI_3_FLASH,
    )


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

        assert result == CreateObservationOutput(observation_id=existing.id, was_created=False)
        # The original row wasn't touched.
        existing.refresh_from_db()
        assert existing.workflow_id != "wf-second"

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
            MarkObservationFailedInputs(observation_id=observation.id, error_reason="bad output")
        )

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.FAILED
        assert observation.error_reason == "bad output"
        assert observation.completed_at is not None

    @pytest.mark.parametrize("terminal_status", [ObservationStatus.SUCCEEDED, ObservationStatus.FAILED])
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
            MarkObservationFailedInputs(observation_id=observation.id, error_reason="late failure")
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
        result = ScannerResult(model_output=MonitorOutput(verdict=True, reasoning="ok", confidence=0.9))

        mark_observation_succeeded_activity(
            MarkObservationSucceededInputs(observation_id=observation.id, scanner_result=result)
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
        result = ScannerResult(model_output=MonitorOutput(verdict=True, reasoning="late", confidence=0.9))

        mark_observation_succeeded_activity(
            MarkObservationSucceededInputs(observation_id=observation.id, scanner_result=result)
        )

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.FAILED
        assert observation.completed_at is not None
        assert observation.scanner_result == {}  # not overwritten


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
        assert stored.events.columns == ["event_id", "event", "timestamp", "$session_id"]
        assert stored.metadata.start_time == start
        assert stored.metadata.end_time == end
        assert stored.metadata.duration_seconds == 300.0
        assert len(stored.events.rows) == 1
        assert stored.events.rows[0][1:] == ["$pageview", "2026-05-12T10:00:00Z", "sess-1"]

    @pytest.mark.asyncio
    async def test_paginates_through_get_events_until_short_page(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": start, "duration": 60, "active_seconds": 30}
        page_size = 3000

        full_page_rows = [("$pageview", start, f"sess-{i}") for i in range(page_size)]
        last_page_rows = [("$pageview", start, "sess-last")]
        mock_obj = self._make_session_replay_events_mock(
            metadata,
            [
                # First page reports more available; second page (short) reports no more, ending the loop.
                (["event", "timestamp", "$session_id"], full_page_rows, True),
                (["event", "timestamp", "$session_id"], last_page_rows, False),
            ],
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

        assert mock_obj.get_events.call_count == 2
        assert mock_obj.get_events.call_args_list[0].kwargs["page"] == 0
        assert mock_obj.get_events.call_args_list[1].kwargs["page"] == 1
        assert mock_obj.get_events.call_args_list[0].kwargs["limit"] == page_size

        redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        stored = await get_data_class_from_redis(redis_client, key, target_class=ScannerLlmInputs)
        assert stored is not None
        assert len(stored.events.rows) == page_size + 1

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

    @pytest.mark.asyncio
    async def test_raises_non_retryable_when_session_active_seconds_exceeds_max(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        metadata = {
            "start_time": dt.datetime(2026, 5, 12, tzinfo=dt.UTC),
            "end_time": dt.datetime(2026, 5, 12, 2, tzinfo=dt.UTC),
            "duration": 7200,
            "active_seconds": 5000,  # over the 3600 cap
        }
        mock_obj = self._make_session_replay_events_mock(metadata, [(["event"], [("$pageview",)])])

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            with pytest.raises(ApplicationError) as exc_info:
                await fetch_session_events_activity(
                    FetchSessionEventsInputs(
                        observation_id=observation_id, team_id=scanner.team_id, session_id="sess-long"
                    )
                )
            assert exc_info.value.non_retryable is True
            assert "5000" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_non_retryable_when_session_has_no_events(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        metadata = {
            "start_time": dt.datetime(2026, 5, 12, tzinfo=dt.UTC),
            "end_time": dt.datetime(2026, 5, 12, 0, 5, tzinfo=dt.UTC),
            "duration": 300,
            "active_seconds": 200,
        }
        mock_obj = self._make_session_replay_events_mock(metadata, [([], [])])

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            with pytest.raises(ApplicationError) as exc_info:
                await fetch_session_events_activity(
                    FetchSessionEventsInputs(
                        observation_id=observation_id,
                        team_id=scanner.team_id,
                        session_id="sess-empty",
                    )
                )
            assert exc_info.value.non_retryable is True

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
        assert "uuid" not in stored.events.columns  # not surfaced to the LLM
        # The mapping records the FIRST uuid seen for each unique event_id.
        assert len(stored.event_id_mapping) == 2
        uuids = {c.uuid for c in stored.event_id_mapping.values()}
        assert "00000000-0000-0000-0000-000000000001" in uuids
        assert "00000000-0000-0000-0000-000000000004" in uuids

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
        assert m.events_truncated is False

    @pytest.mark.asyncio
    async def test_marks_events_truncated_when_last_page_has_more(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": start, "duration": 60, "active_seconds": 30}
        # All 5 pages report has_more=True — we've used the page budget but more events exist.
        full_page = [("$pageview", start, f"sess-{i}") for i in range(3000)]
        pages = [(["event", "timestamp", "$session_id"], full_page, True)] * 5
        mock_obj = self._make_session_replay_events_mock(metadata, pages)

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
        assert stored.metadata.events_truncated is True

    @pytest.mark.asyncio
    async def test_does_not_mark_truncated_when_last_page_exactly_fills_budget(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": start, "duration": 60, "active_seconds": 30}
        # Four full pages with more available, then the fifth full page reports no more.
        full_page = [("$pageview", start, f"sess-{i}") for i in range(3000)]
        pages: list[tuple] = [(["event", "timestamp", "$session_id"], full_page, True)] * 4
        pages.append((["event", "timestamp", "$session_id"], full_page, False))
        mock_obj = self._make_session_replay_events_mock(metadata, pages)

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
        assert stored.metadata.events_truncated is False

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
    ):
        await ApplyScannerWorkflow().run(inputs)


@pytest.mark.asyncio
async def test_apply_scanner_workflow_drives_full_success_pipeline() -> None:
    new_observation_id = uuid.uuid4()
    model_output = MonitorOutput(verdict=True, reasoning="user exported", confidence=0.9)
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=new_observation_id, was_created=True),
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
    assert activity_order[4:] == [
        upload_video_to_gemini_activity,
        call_scanner_provider_activity,
        emit_observation_event_activity,
        mark_observation_succeeded_activity,
        cleanup_gemini_file_activity,
    ]
    assert len(mocks.child_calls) == 1
    assert mocks.child_calls[0][1]["id"] == f"replay-vision-rasterize-99-sess-1-{inputs.scanner_id}"

    emit_input = next(arg for fn, arg in mocks.activity_calls if fn is emit_observation_event_activity)
    assert emit_input.model_output == model_output
    cleanup_input = next(arg for fn, arg in mocks.activity_calls if fn is cleanup_gemini_file_activity)
    assert cleanup_input.gemini_file_name == "files/x"


@pytest.mark.asyncio
async def test_apply_scanner_workflow_marks_failed_when_fetch_raises() -> None:
    new_observation_id = uuid.uuid4()
    fetch_error = ApplicationError("no events", non_retryable=True)
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=new_observation_id, was_created=True),
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
            create_observation_activity: CreateObservationOutput(observation_id=new_observation_id, was_created=True),
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
            create_observation_activity: CreateObservationOutput(observation_id=new_observation_id, was_created=True),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(
                model_output=MonitorOutput(verdict=True, reasoning="ok", confidence=0.9),
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
async def test_apply_scanner_workflow_exits_when_create_returns_was_created_false() -> None:
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=uuid.uuid4(), was_created=False),
        },
    )

    await _run_workflow(_build_inputs(session_id="sess-dup"), mocks)

    assert [fn for fn, _ in mocks.activity_calls] == [create_observation_activity]
    assert mocks.child_calls == []


@pytest.mark.asyncio
async def test_apply_scanner_workflow_propagates_workflow_id_to_create() -> None:
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=uuid.uuid4(), was_created=False),
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


def _indexer_output() -> IndexerOutput:
    return IndexerOutput(
        intent="Log in to the dashboard",
        summary="User tried to authenticate but the form failed twice.",
        outcome="Reached the password reset page after failed attempts.",
        friction_points=["invalid password error"],
        keywords=["login", "authentication", "reset"],
        confidence=0.9,
    )


def _classifier_output() -> ClassifierOutput:
    return ClassifierOutput(
        tags=["support"],
        tags_freeform=["billing"],
        reasoning="user contacted support about billing",
        confidence=0.85,
    )


@pytest.mark.asyncio
async def test_embed_indexer_observation_emits_one_request_per_nonempty_facet() -> None:
    out = IndexerOutput(
        intent="Investigate slow query response",
        summary="User browsed dashboards and clicked through several insights.",
        outcome="No issue reproduced — user closed the tab.",
        friction_points=[],
        keywords=["dashboard", "insight"],
        confidence=0.8,
    )
    inputs = EmbedIndexerObservationInputs(
        team_id=99, session_id="sess-abc", observation_id=uuid.uuid4(), indexer_output=out
    )
    with patch(
        "products.replay_vision.backend.temporal.activities.embed_indexer_observation.emit_embedding_request"
    ) as mock_emit:
        await embed_indexer_observation_activity(inputs)

    renderings = [call.kwargs["rendering"] for call in mock_emit.call_args_list]
    assert renderings == ["intent", "outcome", "keywords"]
    for call in mock_emit.call_args_list:
        assert call.kwargs["team_id"] == 99
        assert call.kwargs["product"] == "replay-vision"
        assert call.kwargs["document_type"] == "replay-observation"
        assert call.kwargs["document_id"] == str(inputs.observation_id)
        assert call.kwargs["models"] == ["text-embedding-3-large-3072"]
        # session_id is carried in metadata so search results can map embeddings → sessions.
        assert call.kwargs["metadata"]["session_id"] == "sess-abc"
        assert call.kwargs["metadata"]["team_id"] == 99
        assert call.kwargs["metadata"]["observation_id"] == str(inputs.observation_id)


@pytest.mark.asyncio
async def test_embed_indexer_observation_raises_propagates_failure() -> None:
    inputs = EmbedIndexerObservationInputs(
        team_id=99, session_id="sess-x", observation_id=uuid.uuid4(), indexer_output=_indexer_output()
    )
    with patch(
        "products.replay_vision.backend.temporal.activities.embed_indexer_observation.emit_embedding_request",
        side_effect=RuntimeError("kafka down"),
    ):
        with pytest.raises(RuntimeError, match="kafka down"):
            await embed_indexer_observation_activity(inputs)


@pytest.mark.asyncio
async def test_emit_classifier_tags_produces_kafka_payload() -> None:
    inputs = EmitClassifierTagsInputs(
        team_id=99, session_id="sess-classify", observation_id=uuid.uuid4(), classifier_output=_classifier_output()
    )
    session_start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
    fake_metadata = {"distinct_id": "user-77", "start_time": session_start}

    with (
        patch(
            "products.replay_vision.backend.temporal.activities.emit_classifier_tags.SessionReplayEvents"
        ) as mock_se_cls,
        patch(
            "products.replay_vision.backend.temporal.activities.emit_classifier_tags.producer_scope"
        ) as mock_producer_scope,
    ):
        mock_se_cls.return_value.get_metadata.return_value = fake_metadata
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
        "products.replay_vision.backend.temporal.activities.emit_classifier_tags.SessionReplayEvents"
    ) as mock_se_cls:
        mock_se_cls.return_value.get_metadata.return_value = None
        with pytest.raises(ApplicationError, match="No replay metadata"):
            await emit_classifier_tags_activity(inputs)


@pytest.mark.asyncio
async def test_embed_indexer_observation_raises_when_kafka_delivery_fails() -> None:
    inputs = EmbedIndexerObservationInputs(
        team_id=99, session_id="sess-x", observation_id=uuid.uuid4(), indexer_output=_indexer_output()
    )
    failed_result = MagicMock()
    failed_result.get.side_effect = RuntimeError("broker timeout")
    with patch(
        "products.replay_vision.backend.temporal.activities.embed_indexer_observation.emit_embedding_request",
        return_value=failed_result,
    ):
        with pytest.raises(RuntimeError, match="broker timeout"):
            await embed_indexer_observation_activity(inputs)


@pytest.mark.asyncio
async def test_emit_classifier_tags_raises_when_kafka_delivery_fails() -> None:
    inputs = EmitClassifierTagsInputs(
        team_id=99, session_id="sess-classify", observation_id=uuid.uuid4(), classifier_output=_classifier_output()
    )
    session_start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
    fake_metadata = {"distinct_id": "user-77", "start_time": session_start}
    failed_result = MagicMock()
    failed_result.get.side_effect = RuntimeError("broker timeout")

    with (
        patch(
            "products.replay_vision.backend.temporal.activities.emit_classifier_tags.SessionReplayEvents"
        ) as mock_se_cls,
        patch(
            "products.replay_vision.backend.temporal.activities.emit_classifier_tags.producer_scope"
        ) as mock_producer_scope,
    ):
        mock_se_cls.return_value.get_metadata.return_value = fake_metadata
        producer = mock_producer_scope.return_value.__enter__.return_value
        producer.produce.return_value = failed_result

        with pytest.raises(RuntimeError, match="broker timeout"):
            await emit_classifier_tags_activity(inputs)


@pytest.mark.asyncio
async def test_apply_scanner_workflow_dispatches_indexer_side_effect() -> None:
    new_observation_id = uuid.uuid4()
    model_output = _indexer_output()
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=new_observation_id, was_created=True),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(model_output=model_output),
        },
    )

    await _run_workflow(_build_inputs(session_id="sess-idx", team_id=99), mocks, workflow_id="wf-idx")

    activity_order = [fn for fn, _ in mocks.activity_calls]
    call_idx = activity_order.index(call_scanner_provider_activity)
    assert activity_order[call_idx + 1] == embed_indexer_observation_activity
    assert activity_order[call_idx + 2] == emit_observation_event_activity
    assert activity_order[call_idx + 3] == mark_observation_succeeded_activity
    assert emit_classifier_tags_activity not in activity_order

    embed_input = next(arg for fn, arg in mocks.activity_calls if fn is embed_indexer_observation_activity)
    assert embed_input.session_id == "sess-idx"
    assert embed_input.team_id == 99
    assert embed_input.indexer_output == model_output


@pytest.mark.asyncio
async def test_apply_scanner_workflow_dispatches_classifier_side_effect() -> None:
    new_observation_id = uuid.uuid4()
    model_output = _classifier_output()
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=new_observation_id, was_created=True),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(model_output=model_output),
        },
    )

    await _run_workflow(_build_inputs(session_id="sess-cls", team_id=99), mocks, workflow_id="wf-cls")

    activity_order = [fn for fn, _ in mocks.activity_calls]
    call_idx = activity_order.index(call_scanner_provider_activity)
    assert activity_order[call_idx + 1] == emit_classifier_tags_activity
    assert activity_order[call_idx + 2] == emit_observation_event_activity
    assert activity_order[call_idx + 3] == mark_observation_succeeded_activity
    assert embed_indexer_observation_activity not in activity_order

    tag_input = next(arg for fn, arg in mocks.activity_calls if fn is emit_classifier_tags_activity)
    assert tag_input.classifier_output == model_output


@pytest.mark.asyncio
async def test_apply_scanner_workflow_skips_side_effects_for_monitor() -> None:
    new_observation_id = uuid.uuid4()
    model_output = MonitorOutput(verdict=True, reasoning="user exported", confidence=0.9)
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=new_observation_id, was_created=True),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(model_output=model_output),
        },
    )

    await _run_workflow(_build_inputs(session_id="sess-mon", team_id=99), mocks, workflow_id="wf-mon")

    called = {fn for fn, _ in mocks.activity_calls}
    assert embed_indexer_observation_activity not in called
    assert emit_classifier_tags_activity not in called


@pytest.mark.asyncio
async def test_apply_scanner_workflow_marks_failed_when_side_effect_raises() -> None:
    new_observation_id = uuid.uuid4()
    side_effect_error = ApplicationError("embedding kafka down", non_retryable=True)
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=new_observation_id, was_created=True),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_scanner_provider_activity: ScannerCallOutput(model_output=_indexer_output()),
        },
        activity_errors={embed_indexer_observation_activity: side_effect_error},
    )

    with pytest.raises(ApplicationError, match="embedding kafka down"):
        await _run_workflow(_build_inputs(session_id="sess-idx-fail"), mocks)

    called = [fn for fn, _ in mocks.activity_calls]
    assert emit_observation_event_activity not in called
    assert mark_observation_succeeded_activity not in called
    assert mark_observation_failed_activity in called
    assert cleanup_gemini_file_activity in called
