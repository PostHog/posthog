from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from parameterized import parameterized

from posthog.api.services.query import ExecutionMode, process_query_dict
from posthog.models.group.util import create_group
from posthog.test.persons import create_group_type_mapping

from products.dashboards.backend.models.dashboard import Dashboard
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.scanner_dashboard import (
    DASHBOARD_SUGGESTION_MIN_OBSERVATIONS,
    create_scanner_dashboard,
)
from products.replay_vision.backend.tests.helpers import snapshot_for

_OUTPUT_BY_TYPE: dict[ScannerType, dict[str, Any]] = {
    ScannerType.MONITOR: {
        "scanner_output_verdict": "yes",
        "scanner_output_confidence": 0.8,
        "scanner_output_reasoning": "The user retried checkout three times.",
    },
    ScannerType.CLASSIFIER: {
        "scanner_output_tags": ["billing", "onboarding"],
        "scanner_output_tags_freeform": ["exports"],
        "scanner_output_reasoning": "Both flows appear.",
    },
    ScannerType.SCORER: {"scanner_output_score": 2.0, "scanner_output_reasoning": "Slow progress."},
    ScannerType.SUMMARIZER: {
        "scanner_output_title": "Set up a dashboard",
        "scanner_output_notability": 0.4,
        "scanner_output_chapter_count": 3,
    },
    ScannerType.EXPERIMENT: {
        "scanner_output_title": "Tried the new pricing page",
        "scanner_output_notability": 0.6,
        "scanner_output_chapter_count": 2,
        "experiment_variant": "test",
    },
}


class _ScannerDashboardTestCase(APIBaseTest):
    def _make_scanner(self, scanner_type: ScannerType = ScannerType.MONITOR) -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=self.team,
            name=f"dashboard-{scanner_type}",
            scanner_type=scanner_type,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )


class TestScannerDashboardTiles(ClickhouseTestMixin, _ScannerDashboardTestCase):
    @parameterized.expand([(scanner_type.value, scanner_type) for scanner_type in ScannerType])
    def test_every_tile_returns_rows_for_observed_recordings(self, _name: str, scanner_type: ScannerType) -> None:
        create_group_type_mapping(
            team=self.team, project_id=self.team.project_id, group_type_index=0, group_type="company"
        )
        create_group(team_id=self.team.pk, group_type_index=0, group_key="acme", properties={"name": "Acme Inc"})
        scanner = self._make_scanner(scanner_type)
        # Trends ignore `$group_0` on events older than the group type mapping, so stamp the events after it.
        observed_at = timezone.now()
        # Three recordings for one company, so that the "at least 3 recordings" account tiles have a row.
        for index in range(3):
            _create_event(
                team=self.team,
                event="$recording_observed",
                distinct_id="replay-vision-system",
                timestamp=observed_at + timedelta(seconds=index),
                properties={
                    "scanner_id": str(scanner.id),
                    "scanner_type": scanner_type.value,
                    "session_id": f"session-{index}",
                    "recording_distinct_id": f"user-{index}",
                    "$group_0": "acme",
                    **_OUTPUT_BY_TYPE[scanner_type],
                },
            )
        flush_persons_and_events()

        dashboard_ref, _ = create_scanner_dashboard(scanner, self.user)

        tiles = list(Dashboard.objects.get(pk=dashboard_ref.id, team=self.team).tiles.select_related("insight"))
        self.assertGreater(len(tiles), 3)
        for tile in tiles:
            insight = tile.insight
            assert insight is not None and insight.query is not None
            query = insight.query
            with self.subTest(insight.name):
                response = process_query_dict(
                    self.team, query["source"], execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS
                )
                payload = response if isinstance(response, dict) else response.model_dump()
                self.assertFalse(payload.get("error"), payload.get("error"))
                results = payload["results"]
                if query["kind"] == "InsightVizNode":
                    self.assertGreater(
                        sum(series.get("aggregated_value") or sum(series["data"]) for series in results),
                        0,
                        insight.name,
                    )
                else:
                    self.assertGreater(len(results), 0)
                if insight.name in ("Top companies", "Lowest scoring companies"):
                    self.assertEqual(results[0][0], "Acme Inc")


class TestScannerDashboardEndpoint(_ScannerDashboardTestCase):
    def _observe(self, scanner: ReplayScanner, count: int, *, days_ago: int = 0) -> None:
        start = ReplayObservation.objects.filter(scanner=scanner).count()
        ReplayObservation.objects.bulk_create(
            ReplayObservation(
                scanner=scanner,
                team=self.team,
                session_id=f"session-{index}",
                status=ObservationStatus.SUCCEEDED,
                scanner_snapshot=snapshot_for(scanner),
                scanner_result={},
                triggered_by=ObservationTrigger.SCHEDULE,
                completed_at=timezone.now() - timedelta(days=days_ago),
            )
            for index in range(start, start + count)
        )

    def _scanner_state(self, scanner: ReplayScanner) -> tuple[int | None, bool]:
        body = self.client.get(f"/api/projects/{self.team.id}/vision/scanners/{scanner.id}/").json()
        return body["dashboard_id"], body["dashboard_suggested"]

    def _create_dashboard(self, scanner: ReplayScanner, expected_status: int) -> int:
        response = self.client.post(f"/api/projects/{self.team.id}/vision/scanners/{scanner.id}/create_dashboard/")
        self.assertEqual(response.status_code, expected_status, response.json())
        return response.json()["dashboard_id"]

    def test_suggests_once_populated_and_links_one_live_dashboard(self) -> None:
        scanner = self._make_scanner()
        # Observations older than the dashboard's date range would chart nothing, so they do not count.
        self._observe(scanner, DASHBOARD_SUGGESTION_MIN_OBSERVATIONS, days_ago=40)
        self.assertEqual(self._scanner_state(scanner), (None, False))

        self._observe(scanner, DASHBOARD_SUGGESTION_MIN_OBSERVATIONS - 1)
        self.assertEqual(self._scanner_state(scanner), (None, False))

        self._observe(scanner, 1)
        self.assertEqual(self._scanner_state(scanner), (None, True))

        dashboard_id = self._create_dashboard(scanner, 201)
        self.assertEqual(self._scanner_state(scanner), (dashboard_id, False))
        self.assertEqual(self._create_dashboard(scanner, 200), dashboard_id)

        Dashboard.objects.filter(pk=dashboard_id).update(deleted=True)
        self.assertEqual(self._scanner_state(scanner), (None, True))
        self.assertNotEqual(self._create_dashboard(scanner, 201), dashboard_id)
