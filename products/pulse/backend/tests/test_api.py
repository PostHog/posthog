from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.pulse.backend.models import PulseDigest, PulseDigestStatus, PulseFinding, PulseSubscription
from products.pulse.backend.temporal.types import CandidateMetric, MetricDescriptor

FLAG_TARGET = "products.pulse.backend.api.posthoganalytics.feature_enabled"


def _make_digest(team: Team, status: str = PulseDigestStatus.DELIVERED, error: dict | None = None) -> PulseDigest:
    with team_scope(team.id):
        now = datetime.now(UTC)
        return PulseDigest.objects.create(
            team=team,
            period_start=now - timedelta(days=7),
            period_end=now,
            status=status,
            error=error,
        )


def _make_finding(
    digest: PulseDigest, team: Team, label: str = "Test metric", rank: int = 0, evidence: dict | None = None
) -> PulseFinding:
    with team_scope(team.id):
        return PulseFinding.objects.create(
            digest=digest,
            team=team,
            metric_descriptor={"source": "top_event", "label": label, "query": {}},
            metric_label=label,
            current_value=100.0,
            baseline_value=80.0,
            change_pct=0.25,
            impact=2.24,
            robust_z=2.5,
            evidence=evidence,
            narrative=f"{label} rose 25%.",
            rank=rank,
        )


class TestPulseFindingSerializerFields(APIBaseTest):
    @patch(FLAG_TARGET, return_value=True)
    def test_finding_exposes_robust_z_and_impact_not_z_score(self, _mock) -> None:
        digest = _make_digest(self.team)
        finding = _make_finding(digest, self.team)
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_findings/{finding.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.json())
        data = resp.json()
        self.assertIn("robust_z", data)
        self.assertIn("impact", data)
        self.assertNotIn("z_score", data)
        self.assertEqual(data["robust_z"], 2.5)
        self.assertEqual(data["impact"], 2.24)

    @patch(FLAG_TARGET, return_value=True)
    def test_finding_exposes_evidence(self, _mock) -> None:
        digest = _make_digest(self.team)
        finding = _make_finding(digest, self.team, evidence={"session_ids": ["abc", "def"]})
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_findings/{finding.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.json())
        self.assertEqual(resp.json()["evidence"], {"session_ids": ["abc", "def"]})

    @patch(FLAG_TARGET, return_value=True)
    def test_subscription_drops_channel_fields(self, _mock) -> None:
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_subscriptions/current/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.json())
        data = resp.json()
        for removed in ("enabled_channels", "slack_channel_id", "email_recipients"):
            self.assertNotIn(removed, data)

    @patch(FLAG_TARGET, return_value=True)
    def test_list_digest_exposes_error_message(self, _mock) -> None:
        _make_digest(self.team, status=PulseDigestStatus.FAILED, error={"message": "ImportError: boom"})
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_digests/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.json())
        results = resp.json()["results"]
        self.assertEqual(results[0]["error"], {"message": "ImportError: boom"})

    @patch(FLAG_TARGET, return_value=True)
    def test_digest_drops_delivered_to(self, _mock) -> None:
        digest = _make_digest(self.team)
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_digests/{digest.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.json())
        self.assertNotIn("delivered_to", resp.json())


class TestPulseDigestAndFindingList(APIBaseTest):
    @patch(FLAG_TARGET, return_value=True)
    def test_list_digests_returns_only_current_team(self, _mock) -> None:
        _make_digest(self.team)
        other_team = self.organization.teams.create(name="other")
        other_team_digest = _make_digest(other_team)
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_digests/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.json())
        ids = [d["id"] for d in resp.json()["results"]]
        self.assertNotIn(str(other_team_digest.id), ids)

    @patch(FLAG_TARGET, return_value=True)
    def test_list_digests_includes_finding_count(self, _mock) -> None:
        digest = _make_digest(self.team)
        _make_finding(digest, self.team)
        _make_finding(digest, self.team, label="Metric B", rank=1)
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_digests/")
        self.assertEqual(resp.json()["results"][0]["finding_count"], 2)

    @patch(FLAG_TARGET, return_value=True)
    def test_retrieve_digest_returns_findings(self, _mock) -> None:
        digest = _make_digest(self.team)
        _make_finding(digest, self.team)
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_digests/{digest.id}/")
        body = resp.json()
        self.assertEqual(body["finding_count"], 1)
        self.assertEqual(len(body["findings"]), 1)

    @patch(FLAG_TARGET, return_value=True)
    def test_list_findings_filters_by_team_via_digest(self, _mock) -> None:
        digest = _make_digest(self.team)
        _make_finding(digest, self.team)
        other_team = self.organization.teams.create(name="other")
        other_digest = _make_digest(other_team)
        _make_finding(other_digest, other_team, label="Other team finding")
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_findings/")
        labels = [f["metric_label"] for f in resp.json()["results"]]
        self.assertEqual(labels, ["Test metric"])


class TestPulseSubscriptionValidation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/environments/{self.team.id}/pulse_subscriptions/"

    @parameterized.expand(
        [
            ("min_change_pct_low", {"min_change_pct": -0.1}),
            ("min_change_pct_high", {"min_change_pct": 1.5}),
            ("baseline_weeks_low", {"baseline_weeks": 0}),
            (
                "baseline_weeks_below_floor",
                {"baseline_weeks": 2},
            ),  # below MIN_BASELINE_WEEKS — must reject, not silently clamp
            ("baseline_weeks_high", {"baseline_weeks": 53}),
            ("max_findings_low", {"max_findings": 0}),
            ("max_findings_high", {"max_findings": 51}),
            ("robust_z_low", {"robust_z_threshold": 0.0}),
            ("robust_z_high", {"robust_z_threshold": 11.0}),
        ]
    )
    @patch(FLAG_TARGET, return_value=True)
    def test_out_of_range_rejected(self, _name, overrides, _mock) -> None:
        resp = self.client.post(self.url, {"enabled": True, **overrides}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.json())

    @patch(FLAG_TARGET, return_value=True)
    def test_discovery_detection_mode_rejected(self, _mock) -> None:
        resp = self.client.post(self.url, {"enabled": True, "detection_mode": "discovery"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.json())
        self.assertIn("detection_mode", str(resp.json()).lower())

    @patch(FLAG_TARGET, return_value=True)
    def test_change_v1_accepted(self, _mock) -> None:
        resp = self.client.post(
            self.url, {"enabled": True, "detection_mode": "change_v1", "min_change_pct": 0.3}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.json())

    @patch(FLAG_TARGET, return_value=True)
    def test_create_then_update(self, _mock) -> None:
        create_resp = self.client.post(self.url, {"enabled": True, "frequency": "weekly"}, format="json")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED, create_resp.json())
        sub_id = create_resp.json()["id"]
        update_resp = self.client.patch(f"{self.url}{sub_id}/", {"frequency": "daily"}, format="json")
        self.assertEqual(update_resp.status_code, status.HTTP_200_OK, update_resp.json())
        self.assertEqual(update_resp.json()["frequency"], "daily")

    @patch(FLAG_TARGET, return_value=True)
    def test_singleton_enforced(self, _mock) -> None:
        with team_scope(self.team.id):
            PulseSubscription.objects.create(team=self.team)
        resp = self.client.post(self.url, {"enabled": True, "frequency": "weekly"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.json())


class TestPulseSubscriptionCurrent(APIBaseTest):
    @patch(FLAG_TARGET, return_value=True)
    def test_current_returns_defaults_when_missing(self, _mock) -> None:
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_subscriptions/current/")
        body = resp.json()
        self.assertIsNone(body["id"])
        self.assertFalse(body["enabled"])
        self.assertEqual(body["frequency"], "weekly")
        self.assertEqual(body["detection_mode"], "change_v1")
        self.assertEqual(body["sensitivity"], "balanced")

    @patch(FLAG_TARGET, return_value=True)
    def test_current_returns_saved_subscription(self, _mock) -> None:
        with team_scope(self.team.id):
            sub = PulseSubscription.objects.create(team=self.team, enabled=True, frequency="daily", max_findings=7)
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_subscriptions/current/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.json())
        body = resp.json()
        self.assertEqual(body["id"], str(sub.id))
        self.assertTrue(body["enabled"])
        self.assertEqual(body["frequency"], "daily")
        self.assertEqual(body["max_findings"], 7)


class TestPulseFlagGate(APIBaseTest):
    @patch(FLAG_TARGET, return_value=False)
    def test_findings_list_404_when_flag_off(self, _mock) -> None:
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_findings/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND, resp.content)

    @patch(FLAG_TARGET, return_value=False)
    def test_digests_list_404_when_flag_off(self, _mock) -> None:
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_digests/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND, resp.content)

    @patch(FLAG_TARGET, return_value=False)
    def test_subscription_current_404_when_flag_off(self, _mock) -> None:
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_subscriptions/current/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND, resp.content)

    @patch(FLAG_TARGET, return_value=True)
    def test_findings_list_200_when_flag_on(self, _mock) -> None:
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_findings/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)


class TestPulseCrossTeamIsolation(APIBaseTest):
    @patch(FLAG_TARGET, return_value=True)
    def test_retrieve_other_teams_finding_404(self, _mock) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_digest = _make_digest(other_team)
        other_finding = _make_finding(other_digest, other_team, label="X")
        resp = self.client.get(f"/api/environments/{self.team.id}/pulse_findings/{other_finding.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND, resp.content)


class TestPulseWatchedEndpoint(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/environments/{self.team.id}/pulse_subscriptions/watched/"

    @patch(FLAG_TARGET, return_value=True)
    @patch("products.pulse.backend.api.select_candidates")
    def test_watched_returns_candidates(self, mock_select, _mock_flag) -> None:
        async def _fake(*_args, **_kwargs):
            return [
                CandidateMetric(
                    descriptor=MetricDescriptor(
                        source="top_event",
                        source_id=42,
                        label="Signups",
                        query={"kind": "TrendsQuery"},
                    )
                )
            ]

        mock_select.side_effect = _fake
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        data = resp.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["label"], "Signups")
        self.assertEqual(data["results"][0]["source"], "top_event")
        self.assertEqual(data["results"][0]["source_id"], "42")

    @patch(FLAG_TARGET, return_value=False)
    def test_watched_404_when_flag_off(self, _mock_flag) -> None:
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND, resp.content)


class TestPulseTriggerScan(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/environments/{self.team.id}/pulse_digests/trigger_scan/"

    def _make_staff(self) -> None:
        self.user.is_staff = True
        self.user.save()

    def _mock_temporal_client(self, captured: dict) -> MagicMock:
        async def _start_workflow(_name: str, inputs, **kwargs) -> None:
            captured["inputs"] = inputs
            captured["kwargs"] = kwargs

        client = MagicMock()
        client.start_workflow = AsyncMock(side_effect=_start_workflow)
        return client

    @patch(FLAG_TARGET, return_value=True)
    def test_non_staff_gets_404(self, _mock_flag) -> None:
        resp = self.client.post(self.url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND, resp.content)

    @patch(FLAG_TARGET, return_value=True)
    @patch("products.pulse.backend.api.async_connect", new_callable=AsyncMock)
    def test_staff_empty_body_starts_scan_without_override(self, mock_connect, _mock_flag) -> None:
        self._make_staff()
        captured: dict = {}
        mock_connect.return_value = self._mock_temporal_client(captured)

        resp = self.client.post(self.url, {}, format="json")

        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertIn("workflow_id", resp.json())
        self.assertIsNone(captured["inputs"].config)

    @patch(FLAG_TARGET, return_value=True)
    @patch("products.pulse.backend.api.async_connect", new_callable=AsyncMock)
    def test_temporal_unavailable_returns_503(self, mock_connect, _mock_flag) -> None:
        self._make_staff()
        mock_connect.side_effect = RuntimeError("temporal down")

        resp = self.client.post(self.url, {}, format="json")

        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE, resp.content)

    @patch(FLAG_TARGET, return_value=True)
    @patch("products.pulse.backend.api.async_connect", new_callable=AsyncMock)
    def test_staff_override_threads_config_into_inputs(self, mock_connect, _mock_flag) -> None:
        self._make_staff()
        captured: dict = {}
        mock_connect.return_value = self._mock_temporal_client(captured)

        body = {"min_baseline_value": 12.0, "top_event_limit": 0, "max_findings": 3, "min_change_pct": 0.5}
        resp = self.client.post(self.url, body, format="json")

        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        config = captured["inputs"].config
        self.assertIsNotNone(config)
        self.assertEqual(config.min_baseline_value, 12.0)
        self.assertEqual(config.top_event_limit, 0)
        self.assertEqual(config.max_findings, 3)
        self.assertEqual(config.min_change_pct, 0.5)
        self.assertEqual(config.dashboard_tile_limit, 10)
        self.assertEqual(config.max_candidates, 200)

    @parameterized.expand(
        [
            ("min_change_pct_too_high", {"min_change_pct": 99}),
            ("min_change_pct_negative", {"min_change_pct": -0.1}),
            ("min_change_pct_zero", {"min_change_pct": 0.0}),
            ("top_event_limit_negative", {"top_event_limit": -1}),
            ("dashboard_tile_limit_over_max", {"dashboard_tile_limit": 201}),
            ("recent_insight_limit_negative", {"recent_insight_limit": -1}),
            ("saved_insight_limit_negative", {"saved_insight_limit": -1}),
            ("max_findings_zero", {"max_findings": 0}),
            ("max_findings_over_max", {"max_findings": 51}),
            ("baseline_weeks_too_low", {"baseline_weeks": 1}),
            ("baseline_weeks_too_high", {"baseline_weeks": 13}),
            ("min_viewers_zero", {"min_viewers_for_recent_insight": 0}),
            ("recent_days_zero", {"recent_days": 0}),
            ("recent_days_over_max", {"recent_days": 366}),
            ("robust_z_too_low", {"robust_z_threshold": 0.05}),
            ("min_baseline_value_negative", {"min_baseline_value": -1}),
            ("max_candidates_zero", {"max_candidates": 0}),
            ("max_candidates_over_max", {"max_candidates": 1001}),
        ]
    )
    @patch(FLAG_TARGET, return_value=True)
    def test_invalid_override_rejected(self, _name: str, body: dict, _mock_flag) -> None:
        self._make_staff()
        resp = self.client.post(self.url, body, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
