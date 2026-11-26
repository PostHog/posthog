from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from rest_framework.test import APIClient

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.meep.backend.models import BoardRun, ChatTurn, Topic
from products.meep.backend.scouts import _open_reports
from products.meep.backend.task_profiles import MEEP, MEEP_MCP_SCOPES
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutRun
from products.tasks.backend.facade import api
from products.tasks.backend.models import TaskRun
from products.workflows.backend.facade.contracts import WorkflowAction


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

    def test_parent_credential_starts_a_child_and_stale_or_child_credentials_cannot_delegate(self):
        create = api.create_and_run_task
        body = {"request_id": str(uuid4()), "title": "Investigate", "brief": "Find the cause."}
        with (
            patch("products.meep.backend.board.check_access"),
            patch(
                "products.meep.backend.board.api.create_and_run_task",
                side_effect=lambda **kwargs: create(**kwargs, start_workflow=False),
            ) as create_child,
        ):
            response = self.agent.post(self.url + "tasks/start/", body, format="json")
            assert response.status_code == 200, response.content
            assert self.agent.post(self.url + "tasks/start/", body, format="json").json() == response.json()
        job = BoardRun.objects.get(run_id=response.json()["run_id"])
        child = TaskRun.objects.get(pk=job.run_id)
        assert child.state["agent_parent_task_id"] == str(self.task_id)
        assert child.state["agent_parent_run_id"] == str(self.task_run.pk)
        assert "meep_task:write" not in create_child.call_args.kwargs["options"].mcp_scopes

        old_turn = ChatTurn.objects.get(run_id=self.task_run.pk)
        old_turn.finished_at = timezone.now()
        old_turn.save(update_fields=["finished_at"])
        ChatTurn.objects.create(topic=self.topic, run_id=uuid4(), message_id=uuid4(), text="A new turn")
        assert (
            self.agent.post(self.url + "tasks/start/", {**body, "request_id": str(uuid4())}, format="json").status_code
            == 403
        )

        self.token.sandbox_task_id = job.task_id
        self.token.save(update_fields=["sandbox_task_id"])
        child.state = {**child.state, "sandbox_oauth_token_ids": [str(self.token.pk)]}
        child.save(update_fields=["state"])
        assert (
            self.agent.post(self.url + "tasks/start/", {**body, "request_id": str(uuid4())}, format="json").status_code
            == 403
        )

    def test_agent_links_a_workflow_as_a_topic_routine_once(self):
        workflow_id = uuid4()
        body = {"workflow_id": str(workflow_id), "name": "Daily report", "trigger": "Every day at 09:00 UTC"}
        with (
            patch("products.meep.backend.routines.workflows.can_edit_workflows", return_value=True),
            patch(
                "products.meep.backend.routines.workflows.workflow_exists",
                side_effect=lambda **kw: kw["workflow_id"] == workflow_id,
            ),
        ):
            first = self.agent.post(self.url + "routines/", body, format="json")
            assert first.status_code == 200, first.content
            assert self.agent.post(self.url + "routines/", body, format="json").status_code == 200
            missing = self.agent.post(self.url + "routines/", {**body, "workflow_id": str(uuid4())}, format="json")
        assert missing.status_code == 404
        self.topic.refresh_from_db()
        bindings = self.topic.state["topic"]["routines"]
        assert [(b["backend"], b["external_id"], b["name"]) for b in bindings] == [
            ("posthog", str(workflow_id), "Daily report")
        ]
        with (
            patch(
                "products.meep.backend.routines.workflows.get_workflow_summary",
                return_value=type("S", (), {"status": "draft", "name": "Daily report"})(),
            ),
            patch(
                "products.meep.backend.routines.workflows.get_workflow_actions",
                return_value=[WorkflowAction(id="trigger", kind="trigger", name="Trigger", description=None)],
            ),
        ):
            shown = self.client.get(
                f"/api/projects/{self.team.pk}/meep/v1/routines/{self.topic.pk}/{bindings[0]['id']}/"
            )
        assert shown.status_code == 200, shown.content
        assert (shown.json()["enabled"], shown.json()["name"]) == (False, "Daily report")
        assert [g["name"] for g in shown.json()["graph"]] == ["Trigger"]

    def test_scout_finding_opens_one_inbox_report_however_often_it_is_delivered(self):
        rows = [
            {
                "reports": [
                    {
                        "id": uuid4(),
                        "title": "No data",
                        "summary": "Events stopped.",
                        "filed_at": "2026-11-26T09:00:00Z",
                    }
                ]
            }
        ]
        for _ in range(2):
            _open_reports(self.topic, rows)
        self.topic.refresh_from_db()
        reports = [t for t in self.topic.state["threads"] if t.get("report_sources")]
        assert [(t["subject"], t["report_sources"]["external"]["provider"]) for t in reports] == [
            ("No data", "posthog-scout")
        ]

    def test_agent_saves_a_goal_a_fact_and_a_rule_once_each(self):
        bodies = [
            {"kind": "goal", "text": "Weekly rage clicks under 200", "current": 270, "target": 200, "unit": "per week"},
            {"kind": "fact", "text": "Events stopped on Nov 6"},
            {"kind": "rule", "text": "Ask before changing a flag", "effect": "ask", "action": "feature-flag-change"},
        ]
        for body in bodies:
            for _ in range(2):
                response = self.agent.post(self.url + "context/", body, format="json")
                assert response.status_code == 200, response.content
        self.topic.refresh_from_db()
        topic = self.topic.state["topic"]
        assert [g["text"] for g in topic["goals"]] == ["Weekly rage clicks under 200"]
        assert [f["text"] for f in topic["facts"]] == ["Events stopped on Nov 6"]
        assert [r["text"] for r in topic["rules"]] == ["Ask before changing a flag"]

    def test_topic_lists_and_reads_files_its_board_tasks_saved(self):
        item_id, run_id = uuid4(), uuid4()
        task_id = uuid4()
        BoardRun.objects.create(topic=self.topic, item_id=item_id, task_id=task_id, run_id=run_id, finished=True)
        entry = {
            "id": "ab12",
            "name": "rows.csv",
            "type": "output",
            "size": 7,
            "content_type": "text/csv",
            "storage_path": "x/y",
        }
        run = type("R", (), {"artifacts": [entry], "created_by_id": self.user.pk})()
        raw = type("Raw", (), {"read": lambda self, n, decode_content=True: b"a,b\n1,2\n"})()
        stored = type(
            "Resp",
            (),
            {
                "headers": {"content-type": "text/csv", "content-length": "8"},
                "raw": raw,
                "raise_for_status": lambda self: None,
            },
        )()
        base = f"/api/projects/{self.team.pk}/meep/v1/topics/{self.topic.pk}/artifacts/"
        with (
            patch("products.meep.backend.board.api.get_task_run", return_value=run),
            patch(
                "products.meep.backend.board.api.presign_task_run_artifact_download",
                return_value=("http://storage/x", None),
            ),
            patch("products.meep.backend.board.requests.get", return_value=stored),
        ):
            listed = self.client.get(base)
            fetched = self.client.get(f"{base}{item_id}/{run_id}/ab12")
        assert listed.status_code == 200, listed.content
        assert [(a["name"], a["task"], a["run"]) for a in listed.json()] == [("rows.csv", str(item_id), str(run_id))]
        assert (fetched.status_code, fetched.content) == (200, b"a,b\n1,2\n")

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
