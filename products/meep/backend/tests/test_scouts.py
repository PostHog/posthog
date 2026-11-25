from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from rest_framework.test import APIClient

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.meep.backend.models import ChatTurn, Topic
from products.meep.backend.task_profiles import MEEP, MEEP_MCP_SCOPES
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutRun
from products.tasks.backend.facade import api
from products.tasks.backend.models import TaskRun


class TestTopicScouts(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        created = api.create_and_run_task(
            team=self.team,
            title="Meep",
            description="Investigate activation",
            user_id=self.user.pk,
            profile=MEEP,
            start_workflow=False,
        )
        self.task_id = created.task_id
        assert created.latest_run
        self.task_run = TaskRun.objects.get(pk=created.latest_run.id)
        self.topic = Topic.objects.for_team(self.team.pk).create(
            team=self.team,
            owner=self.user,
            title="Activation",
            mission="Follow activation",
            conversation_id=self.task_id,
        )
        ChatTurn.objects.create(
            topic=self.topic, run_id=self.task_run.pk, message_id=uuid4(), text="Keep watching activation"
        )
        application = OAuthApplication.objects.create(
            name="Meep task",
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            user=self.user,
        )
        self.token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token=f"pha_task_agent_{uuid4().hex}",
            expires=timezone.now() + timedelta(hours=1),
            scope=" ".join([*MEEP_MCP_SCOPES, "internal_run:read"]),
            scoped_teams=[self.team.id],
            sandbox_task_id=self.task_id,
        )
        self.task_run.state = {**(self.task_run.state or {}), "sandbox_oauth_token_ids": [str(self.token.id)]}
        self.task_run.save(update_fields=["state"])
        self.agent = APIClient()
        self.agent.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token.token}")
        self.url = f"/api/projects/{self.team.pk}/meep/topics/{self.topic.pk}/"
        self.create_body = {
            "name": "Activation scout",
            "instructions": "Look for unusual changes in activation",
            "cron": "0 9 * * *",
        }

    def test_native_scout_retries_pause_resume_and_report_delivery(self):
        created = self.agent.post(self.url + "scouts/", self.create_body, format="json")
        assert created.status_code == 201, created.content
        result = created.json()
        scout = SignalScoutConfig.objects.for_team(self.team.id).get(id=result["id"])
        assert (scout.source_product, scout.source_id, scout.run_cron_schedule, scout.enabled) == (
            "meep",
            str(self.topic.pk),
            "0 9 * * *",
            True,
        )
        assert self.agent.post(self.url + "scouts/", self.create_body, format="json").status_code == 200
        assert (
            self.agent.post(
                self.url + "scout-status/", {"scout_id": uuid4(), "enabled": False}, format="json"
            ).status_code
            == 404
        )
        for enabled in (False, False, True):
            response = self.agent.post(
                self.url + "scout-status/", {"scout_id": scout.id, "enabled": enabled}, format="json"
            )
            assert response.status_code == 200, response.content
            assert response.json()["enabled"] is enabled
            if not enabled:
                assert self.agent.post(self.url + "scouts/", self.create_body, format="json").json()["enabled"] is False
        assert (
            SignalScoutConfig.objects.for_team(self.team.id)
            .filter(source_product="meep", source_id=str(self.topic.pk))
            .count()
            == 1
        )
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="Signup fell", summary="Signup volume fell 25%."
        )
        SignalScoutRun.objects.for_team(self.team.pk).create(
            team=self.team,
            task_run=self.task_run,
            scout_config=scout,
            skill_name=scout.skill_name,
            skill_version=1,
            emitted_report_ids=[str(report.pk)],
        )
        data = self.agent.get(self.url).json()["context"]["scouts"]
        assert data[0]["id"] == result["id"]
        assert data[0]["reports"][0]["id"] == str(report.id)
        changes = f"/api/projects/{self.team.pk}/meep/v1/changes/"
        cache.delete(f"meep:scouts:{self.team.pk}:{self.user.pk}")
        first = self.client.get(changes).json()
        assert first["topics"][0]["state"]["scouts"] == data
        cache.delete(f"meep:scouts:{self.team.pk}:{self.user.pk}")
        assert self.client.get(changes, {"cursor": first["cursor"]}).json()["topics"] == []
        self.token.scope = "meep:read internal_run:read"
        self.token.save(update_fields=["scope"])
        assert self.agent.get(self.url).json()["context"]["scouts"] == []
        report.status = SignalReport.Status.SUPPRESSED
        report.save(update_fields=["status"])
        assert self.client.get(self.url).json()["context"]["scouts"][0]["reports"] == []

    def test_scout_status_only_controls_scouts_owned_by_the_bound_topic(self):
        other = Topic.objects.for_team(self.team.pk).create(
            team=self.team, owner=self.user, title="Other", mission="Elsewhere"
        )
        foreign = SignalScoutConfig.objects.for_team(self.team.id).create(
            team=self.team,
            source_product="meep",
            source_id=str(other.pk),
            skill_name="other-topic-scout",
            enabled=True,
            created_by=self.user,
            enabled_by=self.user,
        )
        request = {"scout_id": str(foreign.pk), "enabled": False}
        assert self.agent.post(self.url + "scout-status/", request, format="json").status_code == 404
        foreign.refresh_from_db()
        assert foreign.enabled

    def test_only_a_bound_meep_run_can_create_for_its_own_topic(self):
        other = Topic.objects.for_team(self.team.pk).create(
            team=self.team, owner=self.user, title="Other", mission="Other topic"
        )
        url = f"/api/projects/{self.team.pk}/meep/topics/{other.pk}/scouts/"
        assert self.agent.post(url, self.create_body, format="json").status_code == 403
        assert self.client.post(self.url + "scouts/", self.create_body, format="json").status_code == 403
        with patch("products.meep.backend.scouts.UserAccessControl") as acl:
            acl.return_value.check_access_level_for_resource.return_value = False
            assert self.agent.post(self.url + "scouts/", self.create_body, format="json").status_code == 403
        with patch("products.signals.backend.scout_harness.views.UserAccessControl") as acl:
            acl.return_value.check_access_level_for_resource.return_value = False
            assert self.agent.post(self.url + "scouts/", self.create_body, format="json").status_code == 403
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        assert self.agent.post(self.url + "scouts/", self.create_body, format="json").status_code == 403
        assert not SignalScoutConfig.objects.for_team(self.team.id).filter(source_product="meep").exists()
