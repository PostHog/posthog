import time
from datetime import timedelta
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import OperationalError, connection
from django.utils import timezone

import psycopg
from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models import ProjectSecretAPIKey, Team
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret

from products.access_control.backend.models.access_control import AccessControl
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_request import ReplayObservationRequest
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.observation_requests import (
    _SWEEP_CURSOR_KEY,
    MAX_SESSION_END_WAIT,
    RequestSession,
    RequestSessionState,
    _complete_page,
    _unanswered_reason,
    complete_settled_requests,
    recording_viewer_access,
    request_progress,
    start_waiting_requests,
)
from products.replay_vision.backend.temporal.constants import APPLY_SCANNER_EXECUTION_TIMEOUT
from products.replay_vision.backend.tests.helpers import create_experiment, snapshot_for


class TestObservationRequestAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Started in setUp, not as class decorators, so @parameterized cases keep their argument order.
        self.start_workflow = self._patch("products.replay_vision.backend.api.trigger.async_to_sync").return_value
        self._patch("products.replay_vision.backend.api.trigger.sync_connect")
        self._patch("products.replay_vision.backend.api.observation_requests.posthoganalytics")
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="checkout",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )

    @property
    def url(self) -> str:
        return f"/api/projects/{self.team.id}/vision/requests/"

    def _psak_client(self, scopes: list[str], team: Team | None = None) -> APIClient:
        raw = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=team or self.team,
            label="ci",
            secure_value=hash_key_value(raw),
            mask_value=f"{raw[:4]}...{raw[-4:]}",
            scopes=scopes,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        return client

    def _patch(self, target: str) -> MagicMock:
        patcher = patch(target)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_project_secret_key_starts_scans_without_a_user(self) -> None:
        client = self._psak_client(["replay_scanner:write", "session_recording:read"])

        response = client.post(
            self.url,
            {"session_ids": ["s1", "s2", "s1"], "scanner_id": str(self.scanner.id), "reference": "job-7"},
            format="json",
        )

        self.assertEqual(response.status_code, 202, response.json())
        body = response.json()
        self.assertEqual(body["status"], "running")
        self.assertEqual(body["reference"], "job-7")
        self.assertEqual(
            [(s["session_id"], s["state"]) for s in body["sessions"]], [("s1", "pending"), ("s2", "pending")]
        )
        inputs = self.start_workflow.call_args.args[1]
        self.assertIsNone(inputs.triggered_by_user_id)
        self.assertEqual(
            ReplayObservationRequest.objects.for_team(self.team.id).get(id=body["id"]).source, "project_secret_api_key"
        )

        read = client.get(f"{self.url}{body['id']}/")
        self.assertEqual(read.status_code, 200, read.json())

    @parameterized.expand(
        [
            ("missing_session_recording_scope", ["replay_scanner:write"], None),
            ("key_from_another_project", ["replay_scanner:write", "session_recording:read"], "other"),
        ]
    )
    def test_project_secret_key_is_refused(self, _name: str, scopes: list[str], team: str | None) -> None:
        other = Team.objects.create(organization=self.organization) if team else None
        client = self._psak_client(scopes, team=other)

        response = client.post(self.url, {"session_ids": ["s1"], "scanner_id": str(self.scanner.id)}, format="json")

        self.assertEqual(response.status_code, 403, response.json())
        self.start_workflow.assert_not_called()

    def test_repeated_idempotency_key_returns_the_first_request_without_starting_scans(self) -> None:
        payload = {"session_ids": ["s1"], "scanner_id": str(self.scanner.id), "idempotency_key": "abc"}

        first = self.client.post(self.url, payload, format="json")
        starts = self.start_workflow.call_count
        second = self.client.post(self.url, {**payload, "session_ids": ["s9"]}, format="json")

        self.assertEqual((first.status_code, second.status_code), (202, 200), second.json())
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(self.start_workflow.call_count, starts)

        # Another caller reusing the key must not read back a request it may not be allowed to see.
        other = self._psak_client(["replay_scanner:write", "session_recording:read"]).post(
            self.url, payload, format="json"
        )
        self.assertEqual(other.status_code, 409, other.json())
        self.assertEqual(self.start_workflow.call_count, starts)

    def test_reading_a_request_hides_rows_recorded_under_an_experiment_the_caller_cannot_view(self) -> None:
        experiment = create_experiment(self.team, "restricted-flag")
        self.scanner.experiment_targeting = {"experiment_id": experiment.id, "variant": "test"}
        self.scanner.save(update_fields=["experiment_targeting"])
        ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id="s1",
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            status=ObservationStatus.RUNNING,
        )
        # Clearing the targeting lets the scanner pass its own gate; the row's snapshot must still block it.
        self.scanner.experiment_targeting = None
        self.scanner.save(update_fields=["experiment_targeting"])
        request = ReplayObservationRequest.objects.for_team(self.team.id).create(
            team=self.team,
            scanner=self.scanner,
            session_ids=["s1"],
            start_outcomes=[{"session_id": "s1", "scan_outcome": "already_scanned"}],
            source="user",
            created_by=self.user,
        )

        with patch(
            "products.access_control.backend.facade.user_access_control.UserAccessControl.filter_queryset_by_access_level",
            side_effect=lambda qs, **_: qs.exclude(pk=experiment.pk) if qs.model is type(experiment) else qs,
        ):
            response = self.client.get(f"{self.url}{request.id}/")

        self.assertEqual(response.status_code, 200, response.json())
        # Neither the row nor whether it is still running may show: `status` reads only the visible rows.
        self.assertEqual((response.json()["sessions"], response.json()["status"]), ([], "completed"))

    @parameterized.expand([("create", "post"), ("retrieve", "get")])
    def test_a_child_environment_cannot_use_scan_requests(self, _name: str, method: str) -> None:
        payload = {"session_ids": ["s1"], "inline": {"prompt": "anything"}, "idempotency_key": "shared"}
        scopes = ["replay_scanner:write", "session_recording:read"]
        parent = self._psak_client(scopes).post(self.url, payload, format="json")
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="child env")
        child_client = self._psak_client(scopes, team=child)
        child_url = f"/api/projects/{child.id}/vision/requests/"

        # Requests are stored under the main environment, so a child must not reach them by key or by id.
        response = (
            child_client.post(child_url, payload, format="json")
            if method == "post"
            else child_client.get(f"{child_url}{parent.json()['id']}/")
        )

        self.assertEqual((parent.status_code, response.status_code), (202, 400), response.json())

    def test_a_request_that_waits_for_the_session_to_end_starts_nothing_yet(self) -> None:
        response = self.client.post(
            self.url,
            {"session_ids": ["s1"], "scanner_id": str(self.scanner.id), "wait_for_session_end": True},
            format="json",
        )

        self.assertEqual(response.status_code, 202, response.json())
        session = response.json()["sessions"][0]
        self.assertEqual(
            (response.json()["status"], session["state"], session["scan_outcome"]), ("running", "pending", None)
        )
        self.start_workflow.assert_not_called()

    def test_inline_question_mints_a_hidden_scanner_and_reports_its_id(self) -> None:

        response = self.client.post(
            self.url, {"session_ids": ["s1"], "inline": {"prompt": "did they rage click?"}}, format="json"
        )

        self.assertEqual(response.status_code, 202, response.json())
        scanner = ReplayScanner.all_origins.get(id=response.json()["scanner_id"])
        self.assertEqual(scanner.origin, "inline")

    @parameterized.expand(
        [
            ("no_ai_consent", {"consent": False}, 400),
            ("both_scanner_and_inline", {"inline": True}, 400),
        ]
    )
    def test_create_is_refused(self, _name: str, case: dict[str, Any], expected: int) -> None:
        if case.get("consent") is False:
            self.organization.is_ai_data_processing_approved = False
            self.organization.save()
        payload: dict[str, Any] = {"session_ids": ["s1"], "scanner_id": str(self.scanner.id)}
        if case.get("inline"):
            payload["inline"] = {"prompt": "x"}

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, expected, response.json())
        self.start_workflow.assert_not_called()
        self.assertFalse(ReplayObservationRequest.objects.for_team(self.team.id).exists())


class TestRequestProgress(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="checkout",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )

    def _observe(self, session_id: str, status: ObservationStatus) -> None:
        ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=session_id,
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            status=status,
            completed_at=timezone.now()
            if status not in (ObservationStatus.PENDING, ObservationStatus.RUNNING)
            else None,
        )

    @parameterized.expand(
        [
            ("still_running", ObservationStatus.RUNNING, timedelta(0), "running", False),
            ("succeeded", ObservationStatus.SUCCEEDED, timedelta(0), "succeeded", True),
            ("row_not_written_yet", None, timedelta(0), "pending", False),
            ("row_never_written", None, APPLY_SCANNER_EXECUTION_TIMEOUT + timedelta(minutes=1), "lost", True),
            (
                "row_stuck_running",
                ObservationStatus.RUNNING,
                APPLY_SCANNER_EXECUTION_TIMEOUT + timedelta(minutes=1),
                "lost",
                True,
            ),
        ]
    )
    def test_session_state_follows_its_observation(
        self, _name: str, status: ObservationStatus | None, age: timedelta, state: str, settled: bool
    ) -> None:
        if status is not None:
            self._observe("s1", status)
        request = ReplayObservationRequest.objects.for_team(self.team.id).create(
            team=self.team,
            scanner=self.scanner,
            session_ids=["s1", "s2"],
            start_outcomes=[
                {"session_id": "s1", "scan_outcome": "started"},
                {"session_id": "s2", "scan_outcome": "skipped_quota"},
            ],
            source="user",
        )

        progress = request_progress(request, now=request.created_at + age)

        self.assertEqual([s.state for s in progress.sessions], [state, "skipped"])
        self.assertEqual(progress.settled, settled)

    @parameterized.expand(
        [
            ("still_starting", timedelta(0), "pending", False),
            ("starter_died", timedelta(hours=1), "failed", True),
        ]
    )
    def test_a_request_whose_scans_are_still_starting_is_not_settled(
        self, _name: str, age: timedelta, state: str, settled: bool
    ) -> None:
        request = ReplayObservationRequest.objects.for_team(self.team.id).create(
            team=self.team, scanner=None, session_ids=["s1"], start_outcomes=[], source="user"
        )

        progress = request_progress(request, now=request.created_at + age)

        self.assertEqual([s.state for s in progress.sessions], [state])
        self.assertEqual(progress.settled, settled)


class TestUnansweredReason:
    @parameterized.expand(
        [
            ("answered", RequestSessionState.SUCCEEDED, "started", "", []),
            (
                "credits_used_up",
                RequestSessionState.SKIPPED,
                "skipped_quota",
                None,
                [
                    "Your organization's Replay Vision credits for this period are used up, so the session wasn't scanned."
                ],
            ),
            (
                "too_short_keeps_the_measurement",
                RequestSessionState.INELIGIBLE,
                "started",
                "too_short:Only 3.2s long; min is 5s",
                ["The session was too short to analyze. Only 3.2s long; min is 5s."],
            ),
            (
                "too_large_drops_raw_error_text",
                RequestSessionState.INELIGIBLE,
                "started",
                "too_large:RECORDING_TOO_LARGE blocks=412",
                ["This recording is too large to render as a video, so there was nothing to watch."],
            ),
            (
                "failed_scan",
                RequestSessionState.FAILED,
                "started",
                "provider_rejected:400 from provider",
                ["The AI provider wouldn't analyze this recording's video."],
            ),
            ("never_started", RequestSessionState.FAILED, "failed", None, ["The scan failed to start."]),
            ("lost", RequestSessionState.LOST, "started", "", ["The scan ran out of time before it finished."]),
        ]
    )
    def test_names_why_the_step_got_no_answer(
        self,
        _name: str,
        state: RequestSessionState,
        scan_outcome: str,
        error_reason: str | None,
        expected: list[str],
    ) -> None:
        observation = None if error_reason is None else ReplayObservation(error_reason=error_reason)
        session = RequestSession(session_id="s1", scan_outcome=scan_outcome, state=state, observation=observation)

        assert _unanswered_reason(session) == expected


class TestCompleteSettledRequests(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flush = patch("products.replay_vision.backend.observation_requests.flush_internal_events_producer")
        self.addCleanup(flush.stop)
        flush.start()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="checkout",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )

    def _request(self, outcomes: dict[str, str], **fields: Any) -> ReplayObservationRequest:
        return ReplayObservationRequest.objects.for_team(self.team.id).create(
            team=self.team,
            scanner=self.scanner,
            session_ids=list(outcomes),
            start_outcomes=[{"session_id": sid, "scan_outcome": outcome} for sid, outcome in outcomes.items()],
            **{"reference": "job-7", "source": "project_secret_api_key", **fields},
        )

    @patch("products.replay_vision.backend.observation_requests.emit_workflow_step_resume")
    @patch("products.replay_vision.backend.observation_requests.produce_internal_event")
    def test_one_owners_access_is_loaded_once_per_page(self, _produce: MagicMock, resume: MagicMock) -> None:
        for key in ("run:step:1", "run:step:2", "run:step:3"):
            self._request({"s1": "skipped_quota"}, source="workflow", idempotency_key=key, created_by=self.user)

        with patch(
            "products.replay_vision.backend.observation_requests.recording_viewer_access",
            wraps=recording_viewer_access,
        ) as load_access:
            complete_settled_requests()

        assert (resume.call_count, load_access.call_count) == (3, 1)

    @patch("products.replay_vision.backend.observation_requests.produce_internal_event")
    def test_the_sweep_still_completes_requests_when_the_cache_is_down(self, _produce: MagicMock) -> None:
        request = self._request({"s1": "skipped_quota"})

        with (
            patch("products.replay_vision.backend.observation_requests.cache.get", side_effect=ConnectionError),
            patch("products.replay_vision.backend.observation_requests.cache.delete", side_effect=ConnectionError),
            patch("products.replay_vision.backend.observation_requests.cache.set", side_effect=ConnectionError),
        ):
            complete_settled_requests()

        request.refresh_from_db()
        assert request.completed_at is not None

    @patch("products.replay_vision.backend.observation_requests.produce_internal_event")
    def test_a_tick_resumes_where_the_last_one_ran_out_of_time_and_wraps_around(self, _produce: MagicMock) -> None:
        first = self._request({"s1": "skipped_quota"})
        second = self._request({"s2": "skipped_quota"})
        cache.set(_SWEEP_CURSOR_KEY, (first.created_at.isoformat(), str(first.id)))

        with patch(
            "products.replay_vision.backend.observation_requests._complete_page", wraps=_complete_page
        ) as complete_page:
            complete_settled_requests()

        assert [page[0].id for page, *_ in (call.args for call in complete_page.call_args_list)] == [
            second.id,
            first.id,
        ]
        assert ReplayObservationRequest.objects.for_team(self.team.id).filter(completed_at__isnull=True).count() == 0
        assert cache.get(_SWEEP_CURSOR_KEY) is None

    def _fail_second_page_read(self, cause: type[Exception]) -> Any:
        page_reads = 0

        def wrapper(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
            nonlocal page_reads
            if sql.startswith("SELECT") and '"completed_at" IS NULL' in sql and "LIMIT" in sql:
                page_reads += 1
                if page_reads == 2:
                    raise OperationalError("statement failed") from cause()
            return execute(sql, params, many, context)

        return connection.execute_wrapper(wrapper)

    @patch("products.replay_vision.backend.observation_requests.produce_internal_event")
    def test_a_nearly_spent_query_budget_announces_nothing(self, produce: MagicMock) -> None:
        request = self._request({"s1": "skipped_quota"})

        assert complete_settled_requests(query_deadline=time.time() + 5) == 0

        produce.assert_not_called()
        request.refresh_from_db()
        assert request.completed_at is None

    @patch("products.replay_vision.backend.observation_requests._SWEEP_PAGE_SIZE", 1)
    @patch("products.replay_vision.backend.observation_requests.produce_internal_event")
    def test_a_canceled_statement_ends_the_tick_and_keeps_its_cursor(self, _produce: MagicMock) -> None:
        first = self._request({"s1": "skipped_quota"})
        second = self._request({"s2": "skipped_quota"})

        with self._fail_second_page_read(psycopg.errors.QueryCanceled):
            assert complete_settled_requests() == 1

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.completed_at is not None
        assert second.completed_at is None
        assert cache.get(_SWEEP_CURSOR_KEY) == (first.created_at.isoformat(), str(first.id))

    @patch("products.replay_vision.backend.observation_requests._SWEEP_PAGE_SIZE", 1)
    @patch("products.replay_vision.backend.observation_requests.produce_internal_event")
    def test_other_database_errors_still_fail_the_sweep(self, _produce: MagicMock) -> None:
        self._request({"s1": "skipped_quota"})
        self._request({"s2": "skipped_quota"})

        with self._fail_second_page_read(psycopg.errors.AdminShutdown), pytest.raises(OperationalError):
            complete_settled_requests()

    @parameterized.expand(
        [
            ("settled_and_delivered", "skipped_quota", None, True),
            ("still_in_flight", "started", None, False),
            ("delivery_failed", "skipped_quota", RuntimeError("kafka down"), False),
        ]
    )
    @patch("products.replay_vision.backend.observation_requests.produce_internal_event")
    def test_completes_only_settled_requests_whose_event_was_delivered(
        self, _name: str, outcome: str, delivery_error: Exception | None, completes: bool, produce: MagicMock
    ) -> None:
        produce.return_value.get.side_effect = delivery_error
        request = self._request({"s1": outcome})

        complete_settled_requests()

        request.refresh_from_db()
        self.assertEqual(request.completed_at is not None, completes)
        if outcome == "started":
            produce.assert_not_called()
            return
        event = produce.call_args.kwargs["event"]
        self.assertEqual(event.event, "$replay_vision_request_completed")
        self.assertEqual(event.properties["reference"], "job-7")
        # Anyone who can add a destination receives the event, so it names no sessions.
        self.assertEqual((event.properties["skipped_count"], "sessions" in event.properties), (1, False))

    @patch("products.replay_vision.backend.observation_requests.produce_internal_event")
    def test_announces_a_request_once(self, produce: MagicMock) -> None:
        self._request({"s1": "skipped_limit"})

        complete_settled_requests()
        complete_settled_requests()

        self.assertEqual(produce.call_count, 1)

    @patch("products.replay_vision.backend.observation_requests._SWEEP_PAGE_SIZE", 1)
    @patch("products.replay_vision.backend.observation_requests.produce_internal_event")
    def test_an_undeliverable_request_does_not_block_newer_ones(self, produce: MagicMock) -> None:
        stuck, fine = MagicMock(), MagicMock()
        stuck.get.side_effect = RuntimeError("kafka refused")
        produce.side_effect = [stuck, fine]
        first = self._request({"s1": "skipped_limit"})
        second = self._request({"s2": "skipped_limit"})

        complete_settled_requests()

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.completed_at is None, second.completed_at is not None), (True, True))

    @parameterized.expand(
        [
            ("workflow_woken", "workflow", None, True, 1, True, "skipped"),
            ("workflow_owner_lost_access", "workflow", None, False, 1, True, "failed"),
            ("workflow_owner_lost_scanner_access", "workflow", None, True, 1, True, "failed"),
            ("workflow_wake_failed", "workflow", RuntimeError("engine down"), True, 1, False, None),
            ("api", "project_secret_api_key", None, True, 0, True, None),
        ]
    )
    @patch("products.replay_vision.backend.observation_requests.emit_workflow_step_resume")
    @patch("products.replay_vision.backend.observation_requests.produce_internal_event")
    def test_wakes_only_the_workflow_step_that_started_it(
        self,
        _name: str,
        source: str,
        wake_error: Exception | None,
        owner_active: bool,
        wakes: int,
        completes: bool,
        state: str | None,
        produce: MagicMock,
        resume: MagicMock,
    ) -> None:
        resume.side_effect = wake_error
        self.user.is_active = owner_active
        self.user.save()
        if _name == "workflow_owner_lost_scanner_access":
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            AccessControl.objects.create(
                team=self.team, resource="replay_scanner", resource_id=str(self.scanner.id), access_level="none"
            )
        request = self._request(
            {"s1": "skipped_quota"}, source=source, idempotency_key="run:step:1", created_by=self.user
        )

        complete_settled_requests()

        request.refresh_from_db()
        self.assertEqual((resume.call_count, request.completed_at is not None), (wakes, completes))
        self.assertEqual(produce.call_count, 0 if wake_error else 1)
        if state is not None:
            kwargs = resume.call_args.kwargs
            self.assertEqual((kwargs["origin_key"], kwargs["status"]), ("run:step:1", "completed"))
            self.assertEqual(kwargs["result"]["state"], state)
            self.assertIsNone(kwargs["result"]["output"])


class TestStartWaitingRequests(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        for target in ("api.trigger.async_to_sync", "api.trigger.sync_connect"):
            patcher = patch(f"products.replay_vision.backend.{target}")
            self.addCleanup(patcher.stop)
            patcher.start()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="checkout",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )

    @parameterized.expand(
        [
            ("quiet_long_enough", timedelta(minutes=40), timedelta(0), True),
            ("still_recording", timedelta(minutes=5), timedelta(0), False),
            ("not_recorded_yet", None, timedelta(0), False),
            ("waited_too_long", timedelta(minutes=5), MAX_SESSION_END_WAIT, True),
        ]
    )
    def test_starts_once_the_session_has_ended(
        self, _name: str, quiet_for: timedelta | None, waited: timedelta, starts: bool
    ) -> None:
        request = ReplayObservationRequest.objects.for_team(self.team.id).create(
            team=self.team,
            scanner=self.scanner,
            session_ids=["s1"],
            start_outcomes=[],
            source="project_secret_api_key",
            wait_for_session_end=True,
        )
        now = request.created_at + waited
        last_activity = {} if quiet_for is None else {"s1": now - quiet_for}

        with patch(
            "products.replay_vision.backend.observation_requests.fetch_session_last_activity",
            return_value=last_activity,
        ):
            start_waiting_requests(now=now)

        request.refresh_from_db()
        self.assertEqual(request.started_at is not None, starts)
        self.assertEqual([o["session_id"] for o in request.start_outcomes], ["s1"] if starts else [])

    @patch("products.replay_vision.backend.observation_requests.MAX_CHECKS_PER_TICK", 1)
    def test_a_request_whose_sessions_never_end_does_not_block_the_next_one(self) -> None:
        stuck, ready = (
            ReplayObservationRequest.objects.for_team(self.team.id).create(
                team=self.team,
                scanner=self.scanner,
                session_ids=[sid],
                start_outcomes=[],
                source="project_secret_api_key",
                wait_for_session_end=True,
            )
            for sid in ("never-ends", "ended")
        )
        now = timezone.now()

        with patch(
            "products.replay_vision.backend.observation_requests.fetch_session_last_activity",
            return_value={"never-ends": now, "ended": now - timedelta(hours=1)},
        ):
            start_waiting_requests(now=now)
            start_waiting_requests(now=now + timedelta(minutes=1))

        stuck.refresh_from_db()
        ready.refresh_from_db()
        self.assertEqual((stuck.started_at is None, ready.started_at is not None), (True, True))

    @parameterized.expand([("lost_recording_access",), ("account_deleted",)])
    def test_a_request_whose_creator_can_no_longer_scan_fails_instead_of_starting(self, case: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        request = ReplayObservationRequest.objects.for_team(self.team.id).create(
            team=self.team,
            scanner=self.scanner,
            session_ids=["s1"],
            start_outcomes=[],
            source="user",
            # A deleted account nulls the creator; that must not read as a service key's request.
            created_by=None if case == "account_deleted" else self.user,
            wait_for_session_end=True,
        )
        if case == "lost_recording_access":
            AccessControl.objects.create(team=self.team, resource="session_recording", access_level="none")
        now = timezone.now()

        with patch(
            "products.replay_vision.backend.observation_requests.fetch_session_last_activity",
            return_value={"s1": now - timedelta(hours=1)},
        ):
            start_waiting_requests(now=now)

        request.refresh_from_db()
        self.assertEqual([o["scan_outcome"] for o in request.start_outcomes], ["failed"])

    def test_a_tick_out_of_time_leaves_its_requests_at_the_front(self) -> None:
        request = ReplayObservationRequest.objects.for_team(self.team.id).create(
            team=self.team,
            scanner=self.scanner,
            session_ids=["s1"],
            start_outcomes=[],
            source="project_secret_api_key",
            wait_for_session_end=True,
        )

        with patch("products.replay_vision.backend.observation_requests.fetch_session_last_activity") as fetch:
            start_waiting_requests(budget_seconds=0)

        request.refresh_from_db()
        fetch.assert_not_called()
        # Never read, so it must not count as checked and drop behind requests that were.
        self.assertIsNone(request.session_end_checked_at)
