import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

from parameterized import parameterized
from rest_framework import status
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.slo.types import SloOperation

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.models import BriefConfig, ProductBrief

_TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}


def _temporal_client() -> MagicMock:
    client = MagicMock()
    client.start_workflow = AsyncMock()
    return client


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch("products.pulse.backend.api.brief.sync_connect")
class TestPulseAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def test_generate_requires_flag(self, mock_connect: MagicMock, mock_flag: MagicMock) -> None:
        mock_flag.return_value = False
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/briefs/generate/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_connect.assert_not_called()

    def test_generate_requires_ai_consent(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/briefs/generate/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # The frontend matches this code to show the consent banner — it is part of the API contract.
        assert response.json()["code"] == "ai_consent_required"
        mock_connect.assert_not_called()

    def test_generate_creates_brief_and_starts_workflow(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        client = _temporal_client()
        mock_connect.return_value = client
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/briefs/generate/",
            {"period": {"period_type": "last_n_days", "days": 14}},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        brief = ProductBrief.objects.for_team(self.team.pk).get(id=response.json()["id"])
        assert brief.status == ProductBrief.Status.GENERATING
        assert brief.trigger == ProductBrief.Trigger.ON_DEMAND
        assert brief.period == {"type": "last_n_days", "days": 14}
        client.start_workflow.assert_called_once()
        assert client.start_workflow.call_args.kwargs["task_queue"] == settings.ANALYTICS_PLATFORM_TASK_QUEUE
        assert client.start_workflow.call_args.kwargs["execution_timeout"] is not None
        # The workflow input carries an SLO config so the interceptor emits started/completed metrics.
        workflow_input = client.start_workflow.call_args.args[1]
        assert workflow_input.slo is not None
        assert workflow_input.slo.operation == SloOperation.PULSE_BRIEF_GENERATION
        assert workflow_input.slo.resource_id == str(brief.id)

    @patch("products.pulse.backend.api.brief.report_user_action")
    def test_generate_while_running_returns_409_without_orphan_brief(
        self, mock_report: MagicMock, mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        client = _temporal_client()
        client.start_workflow.side_effect = WorkflowAlreadyStartedError("pulse-brief-x", "pulse-generate-brief")
        mock_connect.return_value = client
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/briefs/generate/")
        assert response.status_code == status.HTTP_409_CONFLICT
        assert not ProductBrief.objects.for_team(self.team.pk).exists()
        # Contention is a distinct analytics signal from a successful generate.
        assert "pulse brief generation contended" in [call.args[1] for call in mock_report.call_args_list]

    def test_generate_dispatch_failure_returns_500_with_brief_id_and_status(
        self, mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        client = _temporal_client()
        client.start_workflow.side_effect = RuntimeError("temporal down")
        mock_connect.return_value = client
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/briefs/generate/")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        brief = ProductBrief.objects.for_team(self.team.pk).get()
        assert brief.status == ProductBrief.Status.FAILED
        assert "temporal down" in (brief.error or "")
        # The failed row's id+status is returned so the frontend can surface/deep-link it.
        assert response.json()["brief"] == {"id": str(brief.id), "status": ProductBrief.Status.FAILED.value}

    def test_generate_with_unknown_config_returns_400(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        with team_scope(other_team.pk, canonical=True):
            foreign_config = BriefConfig.objects.create(team=other_team, name="foreign")
        for config_id in [str(foreign_config.id), str(uuid.uuid4())]:
            response = self.client.post(
                f"/api/projects/{self.team.id}/pulse/briefs/generate/", {"config_id": config_id}
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST, config_id
            assert "Brief config not found." in str(response.json())
        assert not ProductBrief.objects.for_team(self.team.pk).exists()
        mock_connect.assert_not_called()

    def test_briefs_are_team_scoped(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        with team_scope(other_team.pk, canonical=True):
            other_brief = ProductBrief.objects.create(team=other_team, trigger=ProductBrief.Trigger.ON_DEMAND)
        response = self.client.get(f"/api/projects/{self.team.id}/pulse/briefs/")
        assert response.status_code == status.HTTP_200_OK
        assert str(other_brief.id) not in [row["id"] for row in response.json()["results"]]

    def test_config_crud_roundtrip(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        goal_insight = Insight.objects.create(team=self.team, name="Subscriptions created", query=_TRENDS_QUERY)
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {
                "name": "Feature flags focus",
                "focus_prompt": "flags team",
                "anchors": {"insights": ["abc123"]},
                "goal": "Increase subscription usage",
                "goal_metric": {"insight_short_id": goal_insight.short_id},
            },
            format="json",
        )
        assert create_response.status_code == status.HTTP_201_CREATED, create_response.json()
        assert create_response.json()["goal"] == "Increase subscription usage"
        assert create_response.json()["goal_metric"] == {"insight_short_id": goal_insight.short_id}
        config_id = create_response.json()["id"]
        # API input is {insight_short_id}; the stored shape is discriminated on "type" so
        # non-insight goal sources can be added later without a migration, and reads drop it.
        stored = BriefConfig.objects.for_team(self.team.pk).get(id=config_id)
        assert stored.goal_metric == {"type": "insight", "insight_short_id": goal_insight.short_id}

        list_response = self.client.get(f"/api/projects/{self.team.id}/pulse/brief_configs/")
        assert list_response.status_code == status.HTTP_200_OK
        assert [row["id"] for row in list_response.json()["results"]] == [config_id]

        patch_response = self.client.patch(
            f"/api/projects/{self.team.id}/pulse/brief_configs/{config_id}/",
            {"name": "Renamed", "goal_metric": None},
            format="json",
        )
        assert patch_response.status_code == status.HTTP_200_OK
        assert patch_response.json()["name"] == "Renamed"
        assert patch_response.json()["goal_metric"] is None

        with team_scope(self.team.pk, canonical=True):
            brief = ProductBrief.objects.create(
                team=self.team, config_id=config_id, trigger=ProductBrief.Trigger.ON_DEMAND
            )

        delete_response = self.client.delete(f"/api/projects/{self.team.id}/pulse/brief_configs/{config_id}/")
        assert delete_response.status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(f"/api/projects/{self.team.id}/pulse/brief_configs/").json()["results"] == []
        # Soft delete: brief history keeps its config pointer and the row is recoverable.
        brief.refresh_from_db()
        assert str(brief.config_id) == config_id
        restore_response = self.client.patch(
            f"/api/projects/{self.team.id}/pulse/brief_configs/{config_id}/", {"deleted": False}
        )
        assert restore_response.status_code == status.HTTP_200_OK
        assert [
            row["id"] for row in self.client.get(f"/api/projects/{self.team.id}/pulse/brief_configs/").json()["results"]
        ] == [config_id]

    def test_generate_with_soft_deleted_config_returns_400(
        self, mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        with team_scope(self.team.pk, canonical=True):
            config = BriefConfig.objects.create(team=self.team, name="gone", deleted=True)
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/briefs/generate/", {"config_id": str(config.id)}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Brief config not found." in str(response.json())
        mock_connect.assert_not_called()

    def test_config_focus_prompt_length_capped(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "too long", "goal": "grow", "focus_prompt": "x" * 2001},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "focus_prompt"

    def test_config_settings_round_trip_and_range_validated(
        self, _mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        # Valid knobs persist; an out-of-range knob is rejected at the serializer (wiring guard).
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "Tuned", "goal": "grow", "settings": {"confidence_threshold": 0.8}},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["settings"]["confidence_threshold"] == 0.8

        bad = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "Bad", "goal": "grow", "settings": {"confidence_threshold": 5.0}},
            format="json",
        )
        assert bad.status_code == status.HTTP_400_BAD_REQUEST

    def test_generate_rejects_last_n_days_without_days(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/briefs/generate/",
            {"period": {"period_type": "last_n_days"}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_connect.assert_not_called()

    def test_config_accountability_min_age_days_must_be_positive(
        self, _mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        # A non-positive gate pushes the re-score cutoff to now/future and re-scores every
        # opportunity against a stale baseline — reject it at the edge.
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "bad gate", "goal": "grow", "accountability_min_age_days": 0},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "accountability_min_age_days"

    @parameterized.expand(
        [
            ("not_a_dict", "increase usage"),
            ("missing_short_id", {}),
            ("blank_short_id", {"insight_short_id": ""}),
            ("null_short_id", {"insight_short_id": None}),
        ]
    )
    def test_config_rejects_invalid_goal_metric_shape(
        self, _name: str, goal_metric: object, _mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "Goals", "goal": "grow", "goal_metric": goal_metric},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"].startswith("goal_metric")
        assert not BriefConfig.objects.for_team(self.team.pk).exists()

    def test_config_rejects_goal_metric_insight_not_in_team(
        self, _mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        foreign_insight = Insight.objects.create(team=other_team, name="Foreign")
        for short_id in [foreign_insight.short_id, "missing1"]:
            response = self.client.post(
                f"/api/projects/{self.team.id}/pulse/brief_configs/",
                {"name": "Goals", "goal": "grow", "goal_metric": {"insight_short_id": short_id}},
                format="json",
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST, short_id
            assert "does not exist or does not belong to your team" in str(response.json())
        assert not BriefConfig.objects.for_team(self.team.pk).exists()

    def test_config_rejects_non_trends_goal_metric(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        funnel_insight = Insight.objects.create(
            team=self.team,
            name="Signup funnel",
            query={"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery", "series": []}},
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "Goals", "goal": "grow", "goal_metric": {"insight_short_id": funnel_insight.short_id}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "must be a trends insight" in str(response.json())
        assert not BriefConfig.objects.for_team(self.team.pk).exists()

    @parameterized.expand([("missing", None), ("empty", ""), ("whitespace_only", "   ")])
    def test_config_requires_a_goal(
        self, _name: str, goal: str | None, _mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        # Pursuing a goal is the point of a focus, so every config must state one.
        payload: dict[str, object] = {"name": "Goals"}
        if goal is not None:
            payload["goal"] = goal
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/brief_configs/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "goal"
        assert not BriefConfig.objects.for_team(self.team.pk).exists()

    def test_config_cannot_clear_an_existing_goal(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        created = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "Goals", "goal": "grow"},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        patch_response = self.client.patch(
            f"/api/projects/{self.team.id}/pulse/brief_configs/{created.json()['id']}/",
            {"goal": ""},
            format="json",
        )
        assert patch_response.status_code == status.HTTP_400_BAD_REQUEST, patch_response.json()
        assert patch_response.json()["attr"] == "goal"

    def test_patch_rejects_metric_on_goalless_legacy_config(
        self, _mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        # Goals are required now, but rows created before enforcement can be goalless. Attaching a
        # metric to one without also setting a goal must still be rejected — the metric is unread
        # without a goal. This is the only path that reaches the object-level backstop.
        goal_insight = Insight.objects.create(team=self.team, name="Subscriptions created", query=_TRENDS_QUERY)
        with team_scope(self.team.pk, canonical=True):
            legacy = BriefConfig.objects.create(team=self.team, name="Legacy", goal="")
        patch_response = self.client.patch(
            f"/api/projects/{self.team.id}/pulse/brief_configs/{legacy.id}/",
            {"goal_metric": {"insight_short_id": goal_insight.short_id}},
            format="json",
        )
        assert patch_response.status_code == status.HTTP_400_BAD_REQUEST, patch_response.json()
        assert "A goal metric requires a goal." in str(patch_response.json())
